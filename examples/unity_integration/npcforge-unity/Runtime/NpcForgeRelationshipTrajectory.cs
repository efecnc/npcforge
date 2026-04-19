// NpcForgeRelationshipTrajectory.cs
//
// Runtime mirror of npcforge's Python v0.17.0 trajectory module.
// Per-NPC named-waypoint curve (stranger → tolerated → trusted →
// confidant → intimate — or whatever the writer names). Each memory
// event recorded for this NPC nudges the score; waypoints activate as
// the score crosses their thresholds. Unlike arc stages, trajectory
// is NOT latched: a pattern of lies after hard-earned trust CAN drop
// the NPC back to 'stranger', which matches how relationships
// actually work.
//
// Wiring:
// - Author waypoints on the NPC in the Inspector (or paste from
//   characters.yaml via an export).
// - Reference the same NpcForgeMemoryStore the NPC writes memory
//   events to.
// - Call Evaluate() whenever you need the current waypoint — cheap
//   enough to call every scene transition; cache if running per-frame.
// - SummarizeForPrompt() produces the block Python's
//   summarize_trajectory emits — splice into improv client's prompt
//   alongside the ethics/lens blocks.

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    [Serializable]
    public class NpcForgeTrajectoryWaypoint
    {
        public string id;
        public string label;
        public float min_score;
        public string description = "";
        public string voice_shift = "";
        public List<string> unlocks_knowledge = new List<string>();
    }

    [Serializable]
    public class NpcForgeEventDelta
    {
        public string event_type;
        public float delta;
    }

    [Serializable]
    public class NpcForgeTrajectoryReading
    {
        public float score;
        public NpcForgeTrajectoryWaypoint current;
        public NpcForgeTrajectoryWaypoint nextWaypoint;
        public float distanceToNext;
        public List<Contribution> topEvents = new List<Contribution>();

        [Serializable]
        public struct Contribution
        {
            public string eventType;
            public string summary;
            public float delta;
        }
    }

    public class NpcForgeRelationshipTrajectory : MonoBehaviour
    {
        [Tooltip("The NPC this trajectory belongs to. Must match npc_id " +
                 "on memory events for direct events to count.")]
        [SerializeField] private string npcId;

        [Tooltip("Primary faction id — shared events fold in if set.")]
        [SerializeField] private string primaryFactionId = "";

        [Tooltip("Secondary faction id (optional).")]
        [SerializeField] private string secondaryFactionId = "";

        [Tooltip("Waypoints ordered by min_score ascending. Usually 3-5.")]
        [SerializeField]
        private List<NpcForgeTrajectoryWaypoint> waypoints
            = new List<NpcForgeTrajectoryWaypoint>();

        [Tooltip("Per-NPC event deltas. Entries here OVERRIDE the default " +
                 "table for this NPC — set a value to 0 to zero out a " +
                 "default effect.")]
        [SerializeField]
        private List<NpcForgeEventDelta> eventDeltas
            = new List<NpcForgeEventDelta>();

        [Tooltip("Memory reduction per turn elapsed since each event. " +
                 "0 = no decay.")]
        [SerializeField, Min(0f)] private float decayPerTurn;

        [Tooltip("Required — memory store reference.")]
        [SerializeField] private NpcForgeMemoryStore memoryStore;

        [Tooltip("How many top-weighted events to expose in readings + " +
                 "the prompt block.")]
        [SerializeField, Min(1)] private int maxTopEvents = 3;

        [Header("Events")]
        /// <summary>Fires after Evaluate when the waypoint id differs from
        /// the previously cached one. Payload is (oldWaypointId, newWaypointId).
        /// Hook to UI, music, or audio-mix bridges.</summary>
        public UnityEvent<string, string> onWaypointChanged
            = new UnityEvent<string, string>();

        private string _lastWaypointId = "";

        // ---------------------------------------------------------------
        // Default event deltas — mirror Python's DEFAULT_EVENT_DELTAS
        // ---------------------------------------------------------------

        public static readonly IReadOnlyDictionary<string, float>
            DefaultEventDeltas = new Dictionary<string, float>
        {
            // Builds
            ["gift_given"] = +0.10f,
            ["offer_help"] = +0.12f,
            ["confess_vulnerability"] = +0.18f,
            ["secret_shared"] = +0.25f,
            ["faction_helped"] = +0.08f,
            ["barter"] = +0.02f,
            // Breaks
            ["player_lied"] = -0.20f,
            ["threat"] = -0.15f,
            ["threaten_for_info"] = -0.10f,
            ["intimidate"] = -0.15f,
            ["faction_harmed"] = -0.12f,
            // Neutral / situational
            ["ask_about_npc_other"] = +0.01f,
            ["ask_about_local_events"] = +0.01f,
            ["flirt"] = +0.00f,
            ["dramatic_entrance"] = +0.00f,
        };

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public IReadOnlyList<NpcForgeTrajectoryWaypoint> Waypoints => waypoints;

        /// <summary>Resolve the effective per-event delta table: per-NPC
        /// overrides replace defaults.</summary>
        public Dictionary<string, float> ResolvedEventDeltas()
        {
            var resolved = new Dictionary<string, float>(DefaultEventDeltas);
            if (eventDeltas != null)
            {
                foreach (var e in eventDeltas)
                {
                    if (!string.IsNullOrEmpty(e.event_type))
                        resolved[e.event_type] = e.delta;
                }
            }
            return resolved;
        }

        /// <summary>Compute the current waypoint against the memory store.
        /// Fires onWaypointChanged if the current waypoint id differs
        /// from the previous call's.</summary>
        public NpcForgeTrajectoryReading Evaluate()
        {
            var reading = new NpcForgeTrajectoryReading();
            if (memoryStore == null || waypoints.Count == 0) return reading;

            var deltas = ResolvedEventDeltas();
            int currentTurn = memoryStore.CurrentTurn;

            // Gather visible events (direct + faction-shared) + dedupe.
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

            foreach (var e in visible)
            {
                if (!deltas.TryGetValue(e.event_type, out float baseDelta)
                    || Mathf.Approximately(baseDelta, 0f))
                    continue;

                float contribution;
                if (decayPerTurn > 0f)
                {
                    int turnsElapsed = Math.Max(0, currentTurn - e.turn);
                    float decayed = Mathf.Max(
                        Mathf.Abs(baseDelta) - turnsElapsed * decayPerTurn, 0f);
                    contribution = baseDelta > 0f ? decayed : -decayed;
                }
                else
                {
                    contribution = baseDelta;
                }
                if (Mathf.Approximately(contribution, 0f)) continue;

                reading.score += contribution;
                reading.topEvents.Add(new NpcForgeTrajectoryReading.Contribution
                {
                    eventType = e.event_type,
                    summary = e.summary ?? "",
                    delta = contribution,
                });
            }

            // Sort by absolute contribution + trim.
            reading.topEvents.Sort(
                (a, b) => Mathf.Abs(b.delta).CompareTo(Mathf.Abs(a.delta)));
            if (reading.topEvents.Count > maxTopEvents)
                reading.topEvents = reading.topEvents.GetRange(0, maxTopEvents);

            // Find current + next waypoint.
            var sortedWaypoints = new List<NpcForgeTrajectoryWaypoint>(waypoints);
            sortedWaypoints.Sort((a, b) => a.min_score.CompareTo(b.min_score));
            foreach (var w in sortedWaypoints)
            {
                if (reading.score >= w.min_score) reading.current = w;
                else { reading.nextWaypoint = w; break; }
            }
            reading.distanceToNext = reading.nextWaypoint != null
                ? reading.nextWaypoint.min_score - reading.score
                : 0f;

            // Fire transition event if the waypoint changed.
            string newId = reading.current != null ? reading.current.id : "";
            if (newId != _lastWaypointId)
            {
                onWaypointChanged?.Invoke(_lastWaypointId, newId);
                _lastWaypointId = newId;
            }

            return reading;
        }

        /// <summary>Render the prompt block matching Python's
        /// summarize_trajectory. Returns empty string when no current
        /// waypoint (score below lowest) so the prompt layer can
        /// concatenate safely.</summary>
        public string SummarizeForPrompt(
            NpcForgeTrajectoryReading reading = null)
        {
            reading = reading ?? Evaluate();
            if (reading.current == null) return string.Empty;

            var sb = new StringBuilder();
            sb.AppendLine(
                "Relationship trajectory with this player (your private "
                + "read on how close they've come to you; DO NOT narrate "
                + "the mechanic or name the waypoint to them):");
            sb.AppendLine(
                $"- Current waypoint: {reading.current.label} "
                + $"({reading.current.id}).");
            if (!string.IsNullOrWhiteSpace(reading.current.description))
                sb.AppendLine($"    Meaning: {reading.current.description.Trim()}");
            if (!string.IsNullOrWhiteSpace(reading.current.voice_shift))
                sb.AppendLine(
                    "    Voice shift (composes with other active shifts): "
                    + reading.current.voice_shift.Trim());
            if (reading.current.unlocks_knowledge != null
                && reading.current.unlocks_knowledge.Count > 0)
            {
                sb.AppendLine(
                    "    Unlocked knowledge ids (treat the original gate as "
                    + $"satisfied for these facts): "
                    + string.Join(", ", reading.current.unlocks_knowledge));
            }
            if (reading.nextWaypoint != null)
            {
                sb.AppendLine(
                    $"- Next waypoint after this: {reading.nextWaypoint.label} "
                    + $"({reading.nextWaypoint.id}), would require an additional "
                    + $"{reading.distanceToNext:+0.00;-0.00;0.00} score.");
            }
            if (reading.topEvents.Count > 0)
            {
                sb.AppendLine("- What moved the trajectory most:");
                foreach (var c in reading.topEvents)
                {
                    string sign = c.delta > 0 ? "+" : "−";
                    sb.AppendLine($"    {sign} {c.eventType} — {c.summary.Trim()}");
                }
            }
            sb.Append(
                "Let the current waypoint shape tone — warmth, depth of "
                + "disclosure, willingness to meet the player's eyes. Never "
                + "say the waypoint name aloud; never narrate the progression.");
            return sb.ToString();
        }
    }
}
