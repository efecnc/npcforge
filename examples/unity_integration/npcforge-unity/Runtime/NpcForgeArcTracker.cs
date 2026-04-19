// NpcForgeArcTracker.cs
//
// Runtime mirror of npcforge's Python arc layer (src/npcforge/arcs.py).
// Given:
//   - the NPC's ordered arc stages (authored in the Inspector, or
//     imported from the Python-side characters.yaml via a JSON dump)
//   - an NpcForgeMemoryStore reference (per-NPC + faction-shared events)
//   - an NpcForgeFactionStanding reference (per-faction player standings)
//
// the tracker computes which stages are currently active, records
// fresh latch events back into the memory store on crossover, and
// fires UnityEvents so gameplay code (audio mixes, UI glyphs, music
// hints — none of them audio in the sense we're excluding, but
// broadly "presentation") can react to stage transitions.
//
// The component is self-contained: no coupling to the npcforge CLI.
// Writers either hand-author an arc in the Inspector (fine for small
// casts) or paste the JSON equivalent of NpcArc.model_dump() into the
// Inspector's JSON import field.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    // ---------------------------------------------------------------
    // Structured mirrors of Python schemas (TriggerSpec, ArcStage, NpcArc)
    // ---------------------------------------------------------------

    [Serializable]
    public class NpcForgeTriggerSpec
    {
        [Tooltip("Minimum pivotal-salience events this NPC must have seen.")]
        public int min_pivotal_events;
        [Tooltip("Minimum events of any salience.")]
        public int min_total_events;
        [Tooltip("Event types that must each appear at least once.")]
        public List<string> required_event_types = new List<string>();
        [Tooltip("Faction standing floors — all must be met.")]
        public List<FactionFloor> min_standing = new List<FactionFloor>();
        [Tooltip("Faction standing ceilings — all must be respected.")]
        public List<FactionFloor> max_standing = new List<FactionFloor>();
        [Tooltip("Narrative gate the LLM applies; runtime ignores this.")]
        public string custom_condition = "";
    }

    [Serializable]
    public class FactionFloor
    {
        public string faction_id;
        public float value;
    }

    [Serializable]
    public class NpcForgeArcStage
    {
        public string id;
        public string label;
        public string voice_shift;
        public NpcForgeTriggerSpec trigger = new NpcForgeTriggerSpec();
        public List<string> unlocks_knowledge = new List<string>();
        public string description = "";
    }

    [Serializable]
    public class NpcForgeArcSpec
    {
        public string description = "";
        public List<NpcForgeArcStage> stages = new List<NpcForgeArcStage>();
    }

    // ---------------------------------------------------------------
    // Tracker component
    // ---------------------------------------------------------------

    public class NpcForgeArcTracker : MonoBehaviour
    {
        [Tooltip("NPC id this tracker is for. Must match an id in the " +
                 "memory store's records for direct events to count.")]
        [SerializeField] private string npcId;

        [Tooltip("Primary faction of this NPC. Used to fold faction-shared " +
                 "memory events into the trigger evaluation.")]
        [SerializeField] private string primaryFactionId = "";

        [Tooltip("Optional secondary faction.")]
        [SerializeField] private string secondaryFactionId = "";

        [Tooltip("Arc definition — either author in Inspector or paste the " +
                 "JSON equivalent of Python's NpcArc.model_dump().")]
        [SerializeField] private NpcForgeArcSpec arc = new NpcForgeArcSpec();

        [Tooltip("Required — memory store reference. Tracker queries it " +
                 "for events, and records latch events back into it.")]
        [SerializeField] private NpcForgeMemoryStore memoryStore;

        [Tooltip("Optional — faction standings reference. Stages with " +
                 "min_standing / max_standing need it to evaluate.")]
        [SerializeField] private NpcForgeFactionStanding factionStandings;

        [Header("Events")]
        /// <summary>Fires once per stage when the tracker first detects
        /// the trigger satisfied (and records the latch). Payload is the
        /// stage id.</summary>
        public UnityEvent<string> onStageLatched = new UnityEvent<string>();

        public IReadOnlyList<NpcForgeArcStage> Stages => arc.stages;
        public string NpcId => npcId;

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        /// <summary>Return every stage currently active, most-recent LAST
        /// so callers can iterate for cumulative voice-shift stacking.</summary>
        public List<NpcForgeArcStage> ActiveStages()
        {
            var result = new List<NpcForgeArcStage>();
            var latched = PreviouslyLatchedIds();
            foreach (var stage in arc.stages)
            {
                if (latched.Contains(stage.id) || TriggerSatisfied(stage.trigger))
                    result.Add(stage);
            }
            return result;
        }

        /// <summary>Stages whose trigger is satisfied NOW but haven't been
        /// latched yet. Returned in declaration order.</summary>
        public List<NpcForgeArcStage> NewlyLatchableStages()
        {
            var result = new List<NpcForgeArcStage>();
            var latched = PreviouslyLatchedIds();
            foreach (var stage in arc.stages)
            {
                if (latched.Contains(stage.id)) continue;
                if (IsAlwaysActive(stage.trigger)) continue;
                if (TriggerSatisfied(stage.trigger)) result.Add(stage);
            }
            return result;
        }

        /// <summary>Record latch events for every stage newly eligible.
        /// Fires <see cref="onStageLatched"/> per stage. Typical cadence:
        /// call at the end of a narrative beat, after gameplay code has
        /// already appended the memory events that may have advanced
        /// the arc.</summary>
        public int CommitLatches()
        {
            if (memoryStore == null)
            {
                Debug.LogWarning($"[NpcForgeArcTracker] {npcId}: no memory store assigned; cannot latch.");
                return 0;
            }
            var fresh = NewlyLatchableStages();
            foreach (var stage in fresh)
            {
                memoryStore.Record(
                    npcId: npcId,
                    eventType: NpcForgeArcTracker.LatchEventType,
                    summary: $"arc stage '{stage.id}' latched",
                    salience: MemorySalience.Notable);
                onStageLatched?.Invoke(stage.id);
            }
            return fresh.Count;
        }

        /// <summary>Import an arc definition from a JSON string — typically
        /// produced by Python's NpcArc.model_dump_json(). Handy for keeping
        /// Unity and Python arcs in sync without duplicated authoring.</summary>
        public void ImportArcJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                arc = new NpcForgeArcSpec();
                return;
            }
            arc = JsonUtility.FromJson<NpcForgeArcSpec>(json)
                  ?? new NpcForgeArcSpec();
        }

        // ---------------------------------------------------------------
        // Constants — aligned with Python npcforge.arcs.ARC_LATCH_EVENT_TYPE
        // ---------------------------------------------------------------

        public const string LatchEventType = "arc_latched";

        // ---------------------------------------------------------------
        // Internals
        // ---------------------------------------------------------------

        private HashSet<string> PreviouslyLatchedIds()
        {
            var result = new HashSet<string>();
            if (memoryStore == null) return result;
            foreach (var e in memoryStore.Events)
            {
                if (e.npc_id != npcId) continue;
                if (e.event_type != LatchEventType) continue;
                string id = ParseLatchedStageId(e.summary);
                if (!string.IsNullOrEmpty(id)) result.Add(id);
            }
            return result;
        }

        /// <summary>Parse "arc stage '&lt;id&gt;' latched" into the id.
        /// Public so tests + diagnostic tooling can reuse the same parse
        /// the tracker uses internally.</summary>
        public static string ParseLatchedStageId(string summary)
        {
            if (string.IsNullOrEmpty(summary)) return null;
            const string marker = "arc stage '";
            int i = summary.IndexOf(marker, StringComparison.Ordinal);
            if (i < 0) return null;
            int j = summary.IndexOf('\'', i + marker.Length);
            if (j < 0) return null;
            return summary.Substring(i + marker.Length, j - (i + marker.Length));
        }

        public static bool IsAlwaysActive(NpcForgeTriggerSpec t)
        {
            return t.min_pivotal_events == 0
                && t.min_total_events == 0
                && (t.required_event_types == null || t.required_event_types.Count == 0)
                && (t.min_standing == null || t.min_standing.Count == 0)
                && (t.max_standing == null || t.max_standing.Count == 0)
                && string.IsNullOrWhiteSpace(t.custom_condition);
        }

        private bool TriggerSatisfied(NpcForgeTriggerSpec trigger)
        {
            if (memoryStore == null) return IsAlwaysActive(trigger);

            // Collect events visible to this NPC — direct + faction-shared —
            // excluding latch records (bookkeeping, not narrative history).
            var visible = new List<NpcForgeMemoryEvent>();
            foreach (var e in memoryStore.Events)
            {
                if (e.event_type == LatchEventType) continue;
                bool direct = e.npc_id == npcId;
                bool factionHit = !string.IsNullOrEmpty(e.faction_id)
                    && e.npc_id != npcId
                    && (e.faction_id == primaryFactionId
                        || e.faction_id == secondaryFactionId);
                if (direct || factionHit) visible.Add(e);
            }

            if (trigger.min_total_events > 0 && visible.Count < trigger.min_total_events)
                return false;

            if (trigger.min_pivotal_events > 0)
            {
                int pivotal = 0;
                foreach (var e in visible)
                    if (e.SalienceEnum == MemorySalience.Pivotal) pivotal++;
                if (pivotal < trigger.min_pivotal_events) return false;
            }

            if (trigger.required_event_types != null && trigger.required_event_types.Count > 0)
            {
                var seen = new HashSet<string>();
                foreach (var e in visible) seen.Add(e.event_type);
                foreach (var t in trigger.required_event_types)
                    if (!seen.Contains(t)) return false;
            }

            if (trigger.min_standing != null)
            {
                foreach (var f in trigger.min_standing)
                {
                    float current = factionStandings != null
                        ? factionStandings.GetStanding(f.faction_id) : 0f;
                    if (current < f.value) return false;
                }
            }

            if (trigger.max_standing != null)
            {
                foreach (var f in trigger.max_standing)
                {
                    float current = factionStandings != null
                        ? factionStandings.GetStanding(f.faction_id) : 0f;
                    if (current > f.value) return false;
                }
            }

            return true;
        }
    }
}
