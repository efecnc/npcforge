// NpcForgeFactionStanding.cs
//
// Tracks the player's standing per faction on a -100..+100 scale with
// named thresholds (hostile / wary / neutral / friendly / trusted).
// Runtime component — drop it on a scene root, adjust via code or
// UnityEvents, persist to disk alongside NpcForgeMemoryStore.
//
// Intentionally schema-only: npcforge's Python side reads faction
// *definitions* from factions.yaml; the *player's standing* is a
// runtime concept that lives entirely in Unity (and, later, in the
// other engine plugins). We keep the JSON format simple so a memory
// event like "player_helped_guild" recorded through
// NpcForgeMemoryStore.Record(..., factionId: "miners") can pair with
// an AdjustStanding("miners", +15) call here without needing any
// cross-module glue.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    /// <summary>Named standing thresholds. Values are inclusive lower bounds.</summary>
    public enum FactionStandingTier
    {
        Hostile,    // <= -40
        Wary,       // -40 < x <= -10
        Neutral,    // -10 < x <= 10
        Friendly,   // 10 < x <= 40
        Trusted,    // > 40
    }

    [Serializable]
    public class FactionStandingEntry
    {
        public string faction_id;
        public float standing;
    }

    /// <summary>Payload for <see cref="NpcForgeFactionStanding.onStandingChanged"/>.
    /// Bundled into a single type because UnityEvent supports at most four
    /// generic args and we need five meaningful fields.</summary>
    [Serializable]
    public struct FactionStandingChange
    {
        public string factionId;
        public float newValue;
        public float oldValue;
        public FactionStandingTier newTier;
        public FactionStandingTier oldTier;
    }

    public class NpcForgeFactionStanding : MonoBehaviour
    {
        [Tooltip("Clamp range for standing values. Default -100..+100.")]
        [SerializeField] private float min = -100f;
        [SerializeField] private float max = 100f;

        [Tooltip("Filename under Application.persistentDataPath.")]
        [SerializeField] private string fileName = "npcforge_factions.json";

        [Tooltip("If true, auto-save after every AdjustStanding call.")]
        [SerializeField] private bool autoSave = true;

        [Tooltip("Optional: load from the configured path on Start().")]
        [SerializeField] private bool autoLoadOnStart = true;

        // The serialized storage is a list so Unity's JsonUtility can
        // round-trip it (it can't serialise Dictionary directly).
        [SerializeField] private List<FactionStandingEntry> standings
            = new List<FactionStandingEntry>();

        /// <summary>Concrete UnityEvent subclasses so the Inspector can
        /// actually show these in the event picker. UnityEvent<T> isn't
        /// serialized without a concrete subclass.</summary>
        [Serializable] public class StandingChangedEvent : UnityEvent<FactionStandingChange> { }
        [Serializable] public class TierChangedEvent : UnityEvent<string, FactionStandingTier> { }

        [Header("Events")]
        /// <summary>Fires whenever a standing value changes (any delta).
        /// Payload includes before/after values and before/after tiers.</summary>
        public StandingChangedEvent onStandingChanged = new StandingChangedEvent();

        /// <summary>Fires only when a standing crosses a named tier
        /// threshold. Distinct from onStandingChanged so UI can cheaply
        /// ignore within-tier deltas. Payload is (factionId, newTier).</summary>
        public TierChangedEvent onTierChanged = new TierChangedEvent();

        public string FullPath => Path.Combine(Application.persistentDataPath, fileName);

        private void Start()
        {
            if (autoLoadOnStart) Load();
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public float GetStanding(string factionId)
        {
            if (string.IsNullOrEmpty(factionId)) return 0f;
            for (int i = 0; i < standings.Count; i++)
                if (standings[i].faction_id == factionId) return standings[i].standing;
            return 0f;
        }

        public FactionStandingTier GetTier(string factionId)
            => TierFor(GetStanding(factionId));

        public float SetStanding(string factionId, float value)
        {
            float clamped = Mathf.Clamp(value, min, max);
            float previous = GetStanding(factionId);
            int index = -1;
            for (int i = 0; i < standings.Count; i++)
                if (standings[i].faction_id == factionId) { index = i; break; }
            if (index == -1)
                standings.Add(new FactionStandingEntry { faction_id = factionId, standing = clamped });
            else
                standings[index].standing = clamped;

            var oldTier = TierFor(previous);
            var newTier = TierFor(clamped);
            onStandingChanged?.Invoke(new FactionStandingChange
            {
                factionId = factionId,
                newValue = clamped,
                oldValue = previous,
                newTier = newTier,
                oldTier = oldTier,
            });
            if (oldTier != newTier) onTierChanged?.Invoke(factionId, newTier);

            if (autoSave) Save();
            return clamped;
        }

        /// <summary>Add a delta to the standing (clamped). Returns the new value.</summary>
        public float AdjustStanding(string factionId, float delta)
            => SetStanding(factionId, GetStanding(factionId) + delta);

        public bool IsAlly(string factionId) => GetTier(factionId) >= FactionStandingTier.Friendly;
        public bool IsRival(string factionId) => GetTier(factionId) <= FactionStandingTier.Wary;

        /// <summary>Snapshot of every known faction id plus its standing.
        /// Safe to iterate from Editor code.</summary>
        public IReadOnlyList<FactionStandingEntry> Snapshot => standings;

        // ---------------------------------------------------------------
        // Tier logic
        // ---------------------------------------------------------------

        public static FactionStandingTier TierFor(float value)
        {
            if (value <= -40f) return FactionStandingTier.Hostile;
            if (value <= -10f) return FactionStandingTier.Wary;
            if (value <= 10f) return FactionStandingTier.Neutral;
            if (value <= 40f) return FactionStandingTier.Friendly;
            return FactionStandingTier.Trusted;
        }

        // ---------------------------------------------------------------
        // Persistence (JSON)
        // ---------------------------------------------------------------

        [Serializable]
        private class Dto
        {
            public string schemaVersion = "1";
            public List<FactionStandingEntry> standings;
        }

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Application.persistentDataPath);
                File.WriteAllText(FullPath,
                    JsonUtility.ToJson(
                        new Dto { standings = standings },
                        prettyPrint: true));
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgeFactionStanding] save failed: {ex.Message}");
            }
        }

        public void Load()
        {
            if (!File.Exists(FullPath)) return;
            try
            {
                var dto = JsonUtility.FromJson<Dto>(File.ReadAllText(FullPath));
                if (dto != null && dto.standings != null)
                    standings = dto.standings;
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgeFactionStanding] load failed: {ex.Message}");
            }
        }

        public void Clear()
        {
            standings.Clear();
            if (autoSave) Save();
        }
    }
}
