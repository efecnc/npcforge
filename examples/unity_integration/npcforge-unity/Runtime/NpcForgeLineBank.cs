// NpcForgeLineBank.cs
//
// Runtime mirror of npcforge's Python line_bank module (v0.11.0).
// Loads a pre-generated ``<npc>_lines.unity.json`` file, then picks
// context-matched variants per turn — no LLM call in the hot path.
//
// Unity's JsonUtility can't deserialise ``Dictionary<string, X>``, so
// npcforge's Python side ships a list-shaped companion file
// (``*.unity.json``) alongside the native dict-shaped ``.json``. This
// component reads the Unity companion; the npcforge CLI and Editor
// tooling continue to read the native one. Keep them in sync by
// regenerating both (``LineBank.save`` writes both in one call).
//
// Typical wiring:
//   1. Drop NpcForgeLineBank onto the NPC's GameObject.
//   2. Assign the ``.unity.json`` file via the Inspector (TextAsset).
//   3. Wire NpcForgeMemoryStore + NpcForgeFactionStanding +
//      NpcForgeArcTracker references (optional — the context builder
//      reads what's present).
//   4. From gameplay code, call Pick("greeting") — the component
//      assembles a fresh context each call and picks a match.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    // ---------------------------------------------------------------
    // Data shapes — mirror of the Python dict-shape, reshaped into
    // JsonUtility-friendly list-of-struct entries.
    // ---------------------------------------------------------------

    [Serializable]
    public class NpcForgeLineTag
    {
        public string dimension;
        public string value;
    }

    [Serializable]
    public class NpcForgeLineVariant
    {
        public string text;
        public List<NpcForgeLineTag> tags = new List<NpcForgeLineTag>();
        public float salience_boost;
        public string source = "";
    }

    [Serializable]
    public class NpcForgeLineSlot
    {
        public string id;
        public string description;
        public string default_text = "";
    }

    [Serializable]
    public class NpcForgeLineBankPayload
    {
        public string schema_version = "1";
        public string npc_id;
        public List<SlotEntry> slot_entries = new List<SlotEntry>();
        public List<VariantEntry> variant_entries = new List<VariantEntry>();

        [Serializable]
        public class SlotEntry
        {
            public string key;
            public NpcForgeLineSlot slot;
        }

        [Serializable]
        public class VariantEntry
        {
            public string key;
            public List<NpcForgeLineVariant> list = new List<NpcForgeLineVariant>();
        }
    }

    // ---------------------------------------------------------------
    // Runtime context — the dimension values this turn.
    // ---------------------------------------------------------------

    /// <summary>Projection of the runtime world into the closed
    /// dimension vocabulary. Fields left empty don't match against any
    /// variant tag along that dimension.</summary>
    [Serializable]
    public struct NpcForgeLineContext
    {
        public string disposition_tier;
        public string arc_stage;
        public string mood;
        public string recent_event_type;
        public string time_of_day;
        public string faction_present;

        public string ValueFor(string dimension)
        {
            switch (dimension)
            {
                case "disposition_tier": return disposition_tier ?? "";
                case "arc_stage": return arc_stage ?? "";
                case "mood": return mood ?? "";
                case "recent_event_type": return recent_event_type ?? "";
                case "time_of_day": return time_of_day ?? "";
                case "faction_present": return faction_present ?? "";
                default: return "";
            }
        }
    }

    // ---------------------------------------------------------------
    // Component
    // ---------------------------------------------------------------

    public class NpcForgeLineBank : MonoBehaviour
    {
        [Tooltip("Pre-generated bank JSON — use the *.unity.json file " +
                 "written by npcforge's Python side (the list-shaped " +
                 "companion to the native dict-shaped .json).")]
        [SerializeField] private TextAsset bankJson;

        [Tooltip("If assigned, the component reads from this file at " +
                 "Start() — handy for banks that live outside Assets/ " +
                 "(e.g. under Application.persistentDataPath for patching).")]
        [SerializeField] private string bankFilePath = "";

        [Tooltip("Size of the recently-picked LRU cache. Picks within " +
                 "this window won't repeat unless the context leaves " +
                 "no other matching variant.")]
        [SerializeField, Min(0)] private int lruSize = 8;

        [Header("Events")]
        /// <summary>Fires after every successful Pick — payload is
        /// (slotId, picked text). UI / analytics can subscribe.</summary>
        public UnityEvent<string, string> onLinePicked
            = new UnityEvent<string, string>();

        private NpcForgeLineBankPayload _bank;
        private readonly Queue<string> _recent = new Queue<string>();
        private readonly System.Random _rng = new System.Random();

        public string NpcId => _bank != null ? _bank.npc_id : string.Empty;

        private void Start()
        {
            if (bankJson != null)
            {
                ImportBankJson(bankJson.text);
            }
            else if (!string.IsNullOrEmpty(bankFilePath))
            {
                TryLoadFromPath();
            }
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        /// <summary>Parse the list-shaped bank JSON (Python side's
        /// ``*.unity.json``). Replaces any prior bank.</summary>
        public void ImportBankJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                _bank = null;
                return;
            }
            _bank = JsonUtility.FromJson<NpcForgeLineBankPayload>(json);
            if (_bank == null)
            {
                Debug.LogWarning($"[NpcForgeLineBank] import produced null payload for GO '{name}'");
            }
        }

        /// <summary>Pick a variant matching ``ctx`` from ``slotId``.
        /// Returns ``fallbackWhenMissing`` (or the slot's default_text)
        /// if nothing matches. Never throws on missing-slot / missing-
        /// match — production-safe.</summary>
        public string Pick(
            string slotId,
            NpcForgeLineContext ctx,
            string fallbackWhenMissing = "")
        {
            if (_bank == null || string.IsNullOrEmpty(slotId)) return fallbackWhenMissing;

            var variants = VariantsFor(slotId);
            NpcForgeLineSlot slot = SlotFor(slotId);
            string slotFallback = slot != null ? slot.default_text ?? "" : "";

            if (variants == null || variants.Count == 0)
            {
                string result = !string.IsNullOrEmpty(slotFallback)
                    ? slotFallback : fallbackWhenMissing;
                onLinePicked?.Invoke(slotId, result);
                return result;
            }

            // Candidates: variants whose every tag matches ctx.
            var candidates = new List<NpcForgeLineVariant>();
            foreach (var v in variants)
            {
                if (MatchesContext(v, ctx)) candidates.Add(v);
            }
            if (candidates.Count == 0)
            {
                string result = !string.IsNullOrEmpty(slotFallback)
                    ? slotFallback : fallbackWhenMissing;
                onLinePicked?.Invoke(slotId, result);
                return result;
            }

            // Rank: higher tuple wins. (tag_count, salience_boost, not_recent).
            var best = candidates[0];
            int bestScoreA = TagCount(best);
            float bestScoreB = best.salience_boost;
            int bestScoreC = IsRecent(best) ? 0 : 1;

            var topTies = new List<NpcForgeLineVariant> { best };
            for (int i = 1; i < candidates.Count; i++)
            {
                var v = candidates[i];
                int a = TagCount(v);
                float b = v.salience_boost;
                int c = IsRecent(v) ? 0 : 1;
                int cmp = CompareRanked(a, b, c, bestScoreA, bestScoreB, bestScoreC);
                if (cmp > 0)
                {
                    best = v;
                    bestScoreA = a; bestScoreB = b; bestScoreC = c;
                    topTies.Clear();
                    topTies.Add(v);
                }
                else if (cmp == 0)
                {
                    topTies.Add(v);
                }
            }

            var picked = topTies.Count == 1
                ? topTies[0]
                : topTies[_rng.Next(topTies.Count)];

            RememberPick(picked.text);
            onLinePicked?.Invoke(slotId, picked.text);
            return picked.text;
        }

        /// <summary>Snapshot of picks currently in the LRU cache. Oldest
        /// first. Handy for debug overlays.</summary>
        public IEnumerable<string> RecentlyPicked => _recent;

        public int VariantCount(string slotId)
        {
            var vs = VariantsFor(slotId);
            return vs != null ? vs.Count : 0;
        }

        // ---------------------------------------------------------------
        // Internals
        // ---------------------------------------------------------------

        private void TryLoadFromPath()
        {
            string path = bankFilePath;
            if (!Path.IsPathRooted(path))
            {
                path = Path.Combine(Application.persistentDataPath, path);
            }
            if (!File.Exists(path))
            {
                Debug.LogWarning($"[NpcForgeLineBank] bank file not found at {path}");
                return;
            }
            ImportBankJson(File.ReadAllText(path));
        }

        private NpcForgeLineSlot SlotFor(string slotId)
        {
            if (_bank == null) return null;
            foreach (var e in _bank.slot_entries)
                if (e.key == slotId) return e.slot;
            return null;
        }

        private List<NpcForgeLineVariant> VariantsFor(string slotId)
        {
            if (_bank == null) return null;
            foreach (var e in _bank.variant_entries)
                if (e.key == slotId) return e.list;
            return null;
        }

        /// <summary>True iff every tag on <paramref name="v"/> is satisfied
        /// by <paramref name="ctx"/>. Public so tests + diagnostic tooling
        /// can reuse the exact selector predicate.</summary>
        public static bool MatchesContext(NpcForgeLineVariant v, NpcForgeLineContext ctx)
        {
            if (v.tags == null) return true;
            foreach (var t in v.tags)
            {
                string current = ctx.ValueFor(t.dimension);
                if (string.IsNullOrEmpty(current) || current != t.value)
                    return false;
            }
            return true;
        }

        private static int TagCount(NpcForgeLineVariant v)
            => v.tags != null ? v.tags.Count : 0;

        private bool IsRecent(NpcForgeLineVariant v) => _recent.Contains(v.text);

        private void RememberPick(string text)
        {
            if (lruSize <= 0 || string.IsNullOrEmpty(text)) return;
            _recent.Enqueue(text);
            while (_recent.Count > lruSize) _recent.Dequeue();
        }

        private static int CompareRanked(
            int a1, float b1, int c1,
            int a2, float b2, int c2)
        {
            if (a1 != a2) return a1 > a2 ? 1 : -1;
            if (b1 != b2) return b1 > b2 ? 1 : -1;
            if (c1 != c2) return c1 > c2 ? 1 : -1;
            return 0;
        }
    }
}
