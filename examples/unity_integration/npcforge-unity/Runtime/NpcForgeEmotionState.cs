// NpcForgeEmotionState.cs
//
// Runtime mirror of Python's v0.20.0 emotion module. Plutchik's eight
// primary emotions as a running intensity vector derived on-demand
// from the memory store. Contribution per event decays with turns
// elapsed; dominant emotion shapes delivery (not content) via the
// prompt block.
//
// Deliberately NOT a persistent state component — the memory store is
// the single source of truth, so there's no separate file to maintain.
// Hook this on the same GameObject as the memory store, call
// Compute() whenever you need the current state, and splice
// SummarizeForPrompt() into the improv client's context.

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace Altai.NpcForge
{
    /// <summary>Snapshot of the NPC's current Plutchik emotion vector.
    /// Axes with intensity zero are omitted so the UI and summariser
    /// stay tight — a calm NPC has an empty dictionary.</summary>
    [Serializable]
    public class NpcForgeEmotionStateSnapshot
    {
        public Dictionary<string, float> axes = new Dictionary<string, float>();

        public float Get(string axis)
            => axes.TryGetValue(axis, out float v) ? v : 0f;

        public (string axis, float intensity)? Dominant(float minIntensity = 0.1f)
        {
            if (axes.Count == 0) return null;
            string bestAxis = null;
            float bestValue = 0f;
            foreach (var kv in axes)
            {
                if (kv.Value > bestValue) { bestAxis = kv.Key; bestValue = kv.Value; }
            }
            if (bestValue < minIntensity) return null;
            return (bestAxis, bestValue);
        }

        public List<(string axis, float intensity)> Top(
            int n = 3, float minIntensity = 0.1f)
        {
            var list = new List<(string, float)>();
            foreach (var kv in axes)
                if (kv.Value >= minIntensity) list.Add((kv.Key, kv.Value));
            list.Sort((a, b) => b.Item2.CompareTo(a.Item2));
            if (n > 0 && list.Count > n) list = list.GetRange(0, n);
            return list;
        }
    }

    public class NpcForgeEmotionState : MonoBehaviour
    {
        [Tooltip("NPC this tracker belongs to. Must match npc_id on " +
                 "memory events for direct events to count.")]
        [SerializeField] private string npcId;

        [Tooltip("Primary faction id. Faction-shared events fold in " +
                 "through this slot.")]
        [SerializeField] private string primaryFactionId = "";

        [Tooltip("Secondary faction id (optional).")]
        [SerializeField] private string secondaryFactionId = "";

        [Tooltip("Required — memory store reference. Compute reads " +
                 "events from here on demand.")]
        [SerializeField] private NpcForgeMemoryStore memoryStore;

        [Tooltip("Magnitude reduction per turn elapsed since each " +
                 "event. 0 disables decay; 0.05 matches the Python default.")]
        [SerializeField, Range(0f, 1f)] private float decayPerTurn = 0.05f;

        [Tooltip("Max number of axes surfaced in the prompt block.")]
        [SerializeField, Min(1)] private int maxAxesInBlock = 3;

        [Tooltip("Intensity below which an axis is considered silent " +
                 "and omitted from the summary.")]
        [SerializeField, Range(0f, 1f)] private float minIntensity = 0.1f;

        // ---------------------------------------------------------------
        // Plutchik axes + default deltas — mirror Python's emotion.py
        // ---------------------------------------------------------------

        public static readonly string[] EmotionAxes = {
            "joy", "trust", "fear", "surprise",
            "sadness", "disgust", "anger", "anticipation",
        };

        public static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, float>>
            DefaultEmotionDeltas = new Dictionary<string, IReadOnlyDictionary<string, float>>
        {
            // Hostile
            ["player_lied"] = D(new[] { ("disgust", +0.30f), ("trust", -0.20f), ("anger", +0.15f) }),
            ["threat"] = D(new[] { ("fear", +0.40f), ("anger", +0.30f), ("trust", -0.15f) }),
            ["threaten_for_info"] = D(new[] { ("fear", +0.20f), ("anger", +0.20f), ("trust", -0.10f) }),
            ["intimidate"] = D(new[] { ("fear", +0.30f), ("anger", +0.20f), ("trust", -0.10f) }),
            ["faction_harmed"] = D(new[] { ("anger", +0.30f), ("sadness", +0.15f), ("trust", -0.15f) }),

            // Honorable / warm
            ["gift_given"] = D(new[] { ("joy", +0.30f), ("trust", +0.20f) }),
            ["offer_help"] = D(new[] { ("trust", +0.30f), ("joy", +0.20f) }),
            ["confess_vulnerability"] = D(new[] { ("trust", +0.30f), ("surprise", +0.15f) }),
            ["secret_shared"] = D(new[] { ("trust", +0.40f), ("joy", +0.15f) }),
            ["faction_helped"] = D(new[] { ("joy", +0.25f), ("trust", +0.20f) }),

            ["barter"] = D(new[] { ("anticipation", +0.05f) }),

            ["ask_about_npc_other"] = D(new[] { ("anticipation", +0.10f), ("surprise", +0.05f) }),
            ["ask_about_local_events"] = D(new[] { ("anticipation", +0.08f) }),
            ["ask_about_locket"] = D(new[] { ("anticipation", +0.15f), ("surprise", +0.05f) }),

            ["flirt"] = D(new[] { ("surprise", +0.15f), ("joy", +0.10f), ("anticipation", +0.10f) }),
            ["dramatic_entrance"] = D(new[] { ("surprise", +0.25f), ("anticipation", +0.10f) }),
        };

        private static IReadOnlyDictionary<string, float> D(
            (string axis, float delta)[] entries)
        {
            var d = new Dictionary<string, float>(entries.Length);
            foreach (var (axis, delta) in entries) d[axis] = delta;
            return d;
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public NpcForgeMemoryStore MemoryStoreRef => memoryStore;

        /// <summary>Compute the current state from the memory store.
        /// Returns an empty snapshot when no events are visible or
        /// when every axis has decayed to zero.</summary>
        public NpcForgeEmotionStateSnapshot Compute()
        {
            var snap = new NpcForgeEmotionStateSnapshot();
            if (memoryStore == null) return snap;

            // Collect visible events: direct + faction-shared, dedup
            // across primary / secondary slots.
            var visible = new List<NpcForgeMemoryEvent>();
            var seen = new HashSet<(int, string, string)>();
            foreach (var e in memoryStore.Events)
            {
                bool direct = e.npc_id == npcId;
                bool factionHit = !string.IsNullOrEmpty(e.faction_id)
                    && e.npc_id != npcId
                    && (e.faction_id == primaryFactionId
                        || e.faction_id == secondaryFactionId);
                if (!direct && !factionHit) continue;
                var key = (e.turn, e.event_type, e.summary ?? "");
                if (!seen.Add(key)) continue;
                visible.Add(e);
            }

            int currentTurn = memoryStore.CurrentTurn;
            var running = new Dictionary<string, float>();
            foreach (var e in visible)
            {
                if (!DefaultEmotionDeltas.TryGetValue(
                        e.event_type, out var deltas)) continue;
                int turnsElapsed = Mathf.Max(0, currentTurn - e.turn);
                foreach (var kv in deltas)
                {
                    float baseDelta = kv.Value;
                    if (Mathf.Approximately(baseDelta, 0f)) continue;
                    float contribution;
                    if (decayPerTurn > 0f)
                    {
                        float magnitude = Mathf.Max(
                            Mathf.Abs(baseDelta) - decayPerTurn * turnsElapsed, 0f);
                        contribution = baseDelta > 0f ? magnitude : -magnitude;
                    }
                    else
                    {
                        contribution = baseDelta;
                    }
                    if (Mathf.Approximately(contribution, 0f)) continue;
                    running.TryGetValue(kv.Key, out float sum);
                    running[kv.Key] = sum + contribution;
                }
            }

            // Clamp [0, 1] per axis; drop zeros.
            foreach (var kv in running)
            {
                float clamped = Mathf.Clamp01(kv.Value);
                if (clamped > 0f) snap.axes[kv.Key] = clamped;
            }
            return snap;
        }

        /// <summary>Produce the prompt block Python's
        /// summarize_emotion_state emits. Empty string when no axis is
        /// above ``minIntensity``.</summary>
        public string SummarizeForPrompt(
            NpcForgeEmotionStateSnapshot snap = null)
        {
            snap = snap ?? Compute();
            var top = snap.Top(maxAxesInBlock, minIntensity);
            if (top.Count == 0) return string.Empty;

            var sb = new StringBuilder();
            sb.AppendLine(
                "Current emotional state (YOUR internal feeling — "
                + "shape DELIVERY, never narrate or name the emotion "
                + "aloud):");
            foreach (var (axis, intensity) in top)
                sb.AppendLine($"- {axis}: {intensity:F2}");
            string dominant = top[0].axis;
            sb.Append(
                $"Dominant tone: {dominant}. Let this colour pacing, warmth, "
                + "and word choice. Do not say 'I feel {axis}' — let the "
                + "feeling surface naturally in register. A trust-dominant "
                + "character is slower to deflect; a fear-dominant "
                + "character is clipped and watchful; an "
                + "anticipation-dominant character leans forward in their "
                + "next question.");
            return sb.ToString();
        }
    }
}
