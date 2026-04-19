// NpcForgeEthicsReader.cs
//
// Runtime mirror of Python's v0.16.0 ethics module. Given:
//   - this NPC's ethical profile (authored in the Inspector or
//     imported from characters.yaml via export tooling)
//   - an NpcForgeMemoryStore reference (direct + faction-shared events)
//
// computes the NPC's ethical reading of the player — score per axis,
// top-weighted events, net verdict — and renders the prompt block
// the improv client can splice into its system prompt.
//
// DEFAULT_EVENT_JUDGEMENTS mirrors Python's table line-for-line.
// Designers who customise on the Python side should edit both places
// in lockstep (or drive both from a shared JSON file if they want
// one source of truth).

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace Altai.NpcForge
{
    /// <summary>The five ethical axes. Matches Python's EthicalAxis
    /// Literal exactly so the same judgement table applies on both sides.</summary>
    public enum EthicalAxis
    {
        HonorBound,
        Pragmatic,
        SelfServing,
        Zealot,
        Communal,
    }

    [Serializable]
    public class NpcForgeEthicalProfile
    {
        [Range(0f, 1f)] public float honor_bound;
        [Range(0f, 1f)] public float pragmatic;
        [Range(0f, 1f)] public float self_serving;
        [Range(0f, 1f)] public float zealot;
        [Range(0f, 1f)] public float communal;

        public float Weight(EthicalAxis axis)
        {
            switch (axis)
            {
                case EthicalAxis.HonorBound: return honor_bound;
                case EthicalAxis.Pragmatic: return pragmatic;
                case EthicalAxis.SelfServing: return self_serving;
                case EthicalAxis.Zealot: return zealot;
                case EthicalAxis.Communal: return communal;
                default: return 0f;
            }
        }

        public float Weight(string axisKey)
        {
            switch (axisKey)
            {
                case "honor_bound": return honor_bound;
                case "pragmatic": return pragmatic;
                case "self_serving": return self_serving;
                case "zealot": return zealot;
                case "communal": return communal;
                default: return 0f;
            }
        }

        public List<string> DominantAxes(int topN = 2, float minWeight = 0.4f)
        {
            var pairs = new List<KeyValuePair<string, float>>
            {
                new KeyValuePair<string, float>("honor_bound", honor_bound),
                new KeyValuePair<string, float>("pragmatic", pragmatic),
                new KeyValuePair<string, float>("self_serving", self_serving),
                new KeyValuePair<string, float>("zealot", zealot),
                new KeyValuePair<string, float>("communal", communal),
            };
            pairs.Sort((a, b) => b.Value.CompareTo(a.Value));
            var result = new List<string>();
            foreach (var p in pairs)
            {
                if (p.Value < minWeight) break;
                result.Add(p.Key);
                if (result.Count >= topN) break;
            }
            return result;
        }
    }

    /// <summary>One event's contribution to the reading — exposed for
    /// UI / debug tooling that wants to visualise the trail.</summary>
    [Serializable]
    public struct NpcForgeEthicalContribution
    {
        public string eventType;
        public string summary;
        public float delta;
    }

    [Serializable]
    public class NpcForgeEthicalReading
    {
        public float score;
        public Dictionary<string, float> byAxis = new Dictionary<string, float>();
        public List<NpcForgeEthicalContribution> topEvents
            = new List<NpcForgeEthicalContribution>();
    }

    public class NpcForgeEthicsReader : MonoBehaviour
    {
        [Tooltip("This NPC's ethical profile. Authored in the Inspector " +
                 "or imported from characters.yaml.")]
        [SerializeField] private NpcForgeEthicalProfile profile
            = new NpcForgeEthicalProfile();

        [Tooltip("Required — memory store reference. Reader queries it " +
                 "for direct + faction-shared events.")]
        [SerializeField] private NpcForgeMemoryStore memoryStore;

        [Tooltip("NPC id this reader belongs to. Must match an npc_id in " +
                 "the memory store for direct events to count.")]
        [SerializeField] private string npcId;

        [Tooltip("Primary faction id of this NPC (optional — faction-" +
                 "shared events fold in if set).")]
        [SerializeField] private string primaryFactionId = "";

        [Tooltip("Secondary faction id (optional).")]
        [SerializeField] private string secondaryFactionId = "";

        [Tooltip("How many top-weighted events to include in the reading " +
                 "+ the summary block.")]
        [SerializeField, Min(1)] private int maxTopEvents = 3;

        public NpcForgeEthicalProfile Profile => profile;

        // ---------------------------------------------------------------
        // Default judgement table — mirrors Python's DEFAULT_EVENT_JUDGEMENTS
        // ---------------------------------------------------------------

        public static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, float>>
            DefaultEventJudgements = new Dictionary<string, IReadOnlyDictionary<string, float>>
        {
            // Hostile / dishonorable
            ["player_lied"] = Make(-0.30f, +0.00f, +0.10f, -0.20f, -0.10f),
            ["threat"] = Make(-0.20f, -0.05f, +0.00f, -0.10f, -0.15f),
            ["threaten_for_info"] = Make(-0.15f, +0.05f, +0.10f, -0.05f, -0.10f),
            ["intimidate"] = Make(-0.20f, +0.00f, +0.05f, -0.10f, -0.15f),
            ["faction_harmed"] = Make(-0.10f, +0.00f, +0.05f, -0.05f, -0.20f),

            // Honorable / generous
            ["gift_given"] = Make(+0.15f, +0.00f, -0.05f, +0.00f, +0.20f),
            ["offer_help"] = Make(+0.20f, +0.00f, -0.05f, +0.05f, +0.25f),
            ["confess_vulnerability"] = Make(+0.20f, -0.05f, -0.10f, +0.05f, +0.15f),
            ["secret_shared"] = Make(+0.25f, +0.00f, -0.05f, +0.10f, +0.15f),
            ["faction_helped"] = Make(+0.15f, +0.00f, -0.05f, +0.05f, +0.25f),

            // Transactional
            ["barter"] = Make(+0.00f, +0.10f, +0.05f, +0.00f, +0.00f),

            // Curious / investigative
            ["ask_about_npc_other"] = Make(+0.00f, +0.00f, +0.05f, +0.05f, +0.00f),
            ["ask_about_local_events"] = Make(+0.00f, +0.00f, +0.00f, +0.05f, +0.05f),

            // Theatrical / performative
            ["flirt"] = Make(-0.05f, -0.05f, +0.10f, -0.05f, +0.00f),
            ["dramatic_entrance"] = Make(-0.05f, -0.05f, +0.05f, +0.00f, +0.00f),
        };

        private static IReadOnlyDictionary<string, float> Make(
            float honor, float pragm, float self, float zealot, float communal)
        {
            return new Dictionary<string, float>
            {
                ["honor_bound"] = honor,
                ["pragmatic"] = pragm,
                ["self_serving"] = self,
                ["zealot"] = zealot,
                ["communal"] = communal,
            };
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        /// <summary>Compute the NPC's ethical reading of the player
        /// against the current memory store. Returns an empty reading
        /// (score=0, no events) when the memory store is missing.</summary>
        public NpcForgeEthicalReading Evaluate()
        {
            var result = new NpcForgeEthicalReading();
            if (memoryStore == null) return result;

            // Gather visible events — direct + faction-shared, dedupe
            // across primary/secondary slots (matches Python logic).
            var visible = new List<NpcForgeMemoryEvent>();
            var seenKey = new HashSet<(int, string, string)>();
            foreach (var e in memoryStore.Events)
            {
                bool direct = e.npc_id == npcId;
                bool factionHit = !string.IsNullOrEmpty(e.faction_id)
                    && e.npc_id != npcId
                    && (e.faction_id == primaryFactionId
                        || e.faction_id == secondaryFactionId);
                if (!direct && !factionHit) continue;
                var key = (e.turn, e.event_type, e.summary ?? "");
                if (!seenKey.Add(key)) continue;
                visible.Add(e);
            }

            foreach (var e in visible)
            {
                if (!DefaultEventJudgements.TryGetValue(
                        e.event_type, out var deltas))
                    continue;
                float eventTotal = 0f;
                foreach (var kv in deltas)
                {
                    float stance = profile.Weight(kv.Key);
                    if (stance == 0f || kv.Value == 0f) continue;
                    float contribution = stance * kv.Value;
                    if (!result.byAxis.ContainsKey(kv.Key))
                        result.byAxis[kv.Key] = 0f;
                    result.byAxis[kv.Key] += contribution;
                    eventTotal += contribution;
                }
                if (Mathf.Abs(eventTotal) > 1e-6f)
                {
                    result.topEvents.Add(new NpcForgeEthicalContribution
                    {
                        eventType = e.event_type,
                        summary = e.summary ?? "",
                        delta = eventTotal,
                    });
                    result.score += eventTotal;
                }
            }

            // Sort by absolute contribution, take top N.
            result.topEvents.Sort(
                (a, b) => Mathf.Abs(b.delta).CompareTo(Mathf.Abs(a.delta)));
            if (result.topEvents.Count > maxTopEvents)
                result.topEvents = result.topEvents.GetRange(0, maxTopEvents);
            return result;
        }

        /// <summary>Render the reading as the prompt block shape Python's
        /// summarize_ethical_reading produces. Returns empty string when
        /// nothing has been judged.</summary>
        public string SummarizeReading(NpcForgeEthicalReading reading = null)
        {
            reading = reading ?? Evaluate();
            if (reading.topEvents.Count == 0 && Mathf.Abs(reading.score) < 0.001f)
                return string.Empty;

            var dominant = profile.DominantAxes();
            string stance = dominant.Count > 0
                ? string.Join(", ", dominant)
                : "(no dominant axis)";
            string verdict =
                reading.score > 0.1f ? "net approving" :
                reading.score < -0.1f ? "net disapproving" :
                "mixed";

            var sb = new StringBuilder();
            sb.AppendLine(
                "Ethical reading (YOUR private judgement of the player — "
                + "you do not narrate this as a list; you let it shape "
                + "the tone you address them with):");
            sb.AppendLine($"- Your dominant ethical axes: {stance}.");
            sb.AppendLine($"- Net read on the player, weighted by YOUR values: "
                + $"{verdict} (score {reading.score:+0.00;-0.00;+0.00}).");
            if (reading.topEvents.Count > 0)
            {
                sb.AppendLine("- What moved the reading (most recent / most weighty first):");
                foreach (var c in reading.topEvents)
                {
                    string sign = c.delta > 0 ? "+" : "−";
                    sb.AppendLine($"    {sign} {c.eventType} — {c.summary.Trim()}");
                }
            }
            sb.Append(
                "React to the player in a way consistent with this reading. "
                + "If the reading is disapproving on an axis that matters to you, "
                + "let that shape register, not the words — no lectures, no "
                + "moralising, no listing of transgressions. A cooler greeting "
                + "or an edge of withdrawn warmth is enough.");
            return sb.ToString();
        }
    }
}
