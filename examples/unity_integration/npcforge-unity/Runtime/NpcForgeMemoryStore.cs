// NpcForgeMemoryStore.cs
//
// Runtime mirror of npcforge's Python memory layer (src/npcforge/memory.py).
// Records what happened between the player and any NPC so subsequent
// scene / walk-up generation can inject the right recency-sorted context.
//
// JSON format matches the Python side byte-for-byte:
//
//   {
//     "schemaVersion": "1",
//     "currentTurn": 7,
//     "events": [
//       {
//         "turn": 3,
//         "npc_id": "mira_vesser",
//         "event_type": "player_lied",
//         "summary": "The player denied knowing Kess, then named him one breath later.",
//         "salience": "pivotal",
//         "faction_id": ""
//       },
//       ...
//     ]
//   }
//
// Read the same file from Python via MemoryStore.load(Path) and vice
// versa. The runtime persists to Application.persistentDataPath by
// default; the Python CLI operates on <demo-dir>/memory.json. Writers
// can keep them in sync by symlinking or by having the runtime write
// next to the project.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    /// <summary>Recency/decay classification for memory events. Same
    /// three values as the Python <c>MemorySalience</c> Literal.</summary>
    public enum MemorySalience
    {
        Trivial,
        Notable,
        Pivotal,
    }

    [Serializable]
    public class NpcForgeMemoryEvent
    {
        // JSON field names are snake_case to match the Python schema.
        // Unity's JsonUtility maps C# field names verbatim, so we keep
        // them snake_case too and expose pretty-cased properties.
        public int turn;
        public string npc_id;
        public string event_type;
        public string summary;
        public string salience = "notable";
        public string faction_id = "";

        [NonSerialized] private MemorySalience _cachedSalience;
        [NonSerialized] private bool _salienceCached;

        /// <summary>Enum view of the serialized salience string. Defaults
        /// to Notable when the string is missing or malformed.</summary>
        public MemorySalience SalienceEnum
        {
            get
            {
                if (_salienceCached) return _cachedSalience;
                _cachedSalience = ParseSalience(salience);
                _salienceCached = true;
                return _cachedSalience;
            }
            set
            {
                _cachedSalience = value;
                _salienceCached = true;
                salience = FormatSalience(value);
            }
        }

        internal static MemorySalience ParseSalience(string s)
        {
            if (string.IsNullOrEmpty(s)) return MemorySalience.Notable;
            switch (s.ToLowerInvariant())
            {
                case "trivial": return MemorySalience.Trivial;
                case "pivotal": return MemorySalience.Pivotal;
                default: return MemorySalience.Notable;
            }
        }

        internal static string FormatSalience(MemorySalience s)
        {
            switch (s)
            {
                case MemorySalience.Trivial: return "trivial";
                case MemorySalience.Pivotal: return "pivotal";
                default: return "notable";
            }
        }
    }

    /// <summary>Persistable event log — drop one on a scene root
    /// GameObject and call <see cref="Record"/> from gameplay code.</summary>
    public class NpcForgeMemoryStore : MonoBehaviour
    {
        /// <summary>Decay horizon for trivial events (turns). Events older
        /// than this count are omitted from the summary.</summary>
        public const int DecayHorizonTrivial = 3;
        /// <summary>Decay horizon for notable events (turns).</summary>
        public const int DecayHorizonNotable = 10;

        [Tooltip("Filename under Application.persistentDataPath. Matches " +
                 "Python's demo-dir/memory.json name when you copy it in.")]
        [SerializeField] private string fileName = "npcforge_memory.json";

        [Tooltip("If true, auto-save after every Record / AdvanceTurn. " +
                 "Turn off for batch updates and call Save() once at the end.")]
        [SerializeField] private bool autoSave = true;

        [Tooltip("Optional: load from the configured path on Start().")]
        [SerializeField] private bool autoLoadOnStart = true;

        [SerializeField] private int currentTurn;
        [SerializeField] private List<NpcForgeMemoryEvent> events = new List<NpcForgeMemoryEvent>();

        [Header("Events")]
        public UnityEvent<NpcForgeMemoryEvent> onRecorded = new UnityEvent<NpcForgeMemoryEvent>();

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public int CurrentTurn => currentTurn;
        public IReadOnlyList<NpcForgeMemoryEvent> Events => events;
        public string FullPath => Path.Combine(Application.persistentDataPath, fileName);

        private void Start()
        {
            if (autoLoadOnStart) Load();
        }

        /// <summary>Bump the monotonic turn counter. Returns the new value.</summary>
        public int AdvanceTurn(int by = 1)
        {
            currentTurn = Math.Max(0, currentTurn + by);
            if (autoSave) Save();
            return currentTurn;
        }

        /// <summary>Record a new event and fire <see cref="onRecorded"/>.
        /// When <paramref name="turn"/> is negative we use the current turn.</summary>
        public NpcForgeMemoryEvent Record(
            string npcId,
            string eventType,
            string summary,
            MemorySalience salience = MemorySalience.Notable,
            string factionId = "",
            int turn = -1)
        {
            if (string.IsNullOrEmpty(npcId))
                throw new ArgumentException("npcId is required", nameof(npcId));
            if (string.IsNullOrEmpty(eventType))
                throw new ArgumentException("eventType is required", nameof(eventType));

            var e = new NpcForgeMemoryEvent
            {
                turn = turn < 0 ? currentTurn : turn,
                npc_id = npcId,
                event_type = eventType,
                summary = summary ?? string.Empty,
                faction_id = factionId ?? string.Empty,
            };
            e.SalienceEnum = salience;
            events.Add(e);
            onRecorded?.Invoke(e);
            if (autoSave) Save();
            return e;
        }

        /// <summary>Every event this NPC should remember, most-recent first.
        /// Includes events tagged with either of the NPC's faction ids so
        /// "the Guild remembers" dynamics work without per-member records.</summary>
        public List<NpcForgeMemoryEvent> ForNpc(
            string npcId,
            string primaryFactionId = "",
            string secondaryFactionId = "",
            bool includeDecayed = false)
        {
            var result = new List<NpcForgeMemoryEvent>();
            var seen = new HashSet<(int, string, string)>();
            foreach (var e in events)
            {
                bool direct = e.npc_id == npcId;
                bool factionHit =
                    (!string.IsNullOrEmpty(primaryFactionId) && e.faction_id == primaryFactionId && e.npc_id != npcId)
                    || (!string.IsNullOrEmpty(secondaryFactionId) && e.faction_id == secondaryFactionId && e.npc_id != npcId);
                if (!direct && !factionHit) continue;
                if (!includeDecayed && !StillSalient(e, currentTurn)) continue;

                // Dedup on (turn, event_type, summary) so a double-faction
                // match never surfaces the same event twice.
                var key = (e.turn, e.event_type, e.summary);
                if (!seen.Add(key)) continue;
                result.Add(e);
            }
            result.Sort((a, b) => b.turn.CompareTo(a.turn));
            return result;
        }

        /// <summary>Every event tagged with this faction. Factions have
        /// institutional memory — decay is skipped.</summary>
        public List<NpcForgeMemoryEvent> ForFaction(string factionId)
        {
            var result = new List<NpcForgeMemoryEvent>();
            if (string.IsNullOrEmpty(factionId)) return result;
            foreach (var e in events)
            {
                if (e.faction_id == factionId) result.Add(e);
            }
            result.Sort((a, b) => b.turn.CompareTo(a.turn));
            return result;
        }

        /// <summary>Render a prompt-ready text summary of this NPC's memory.
        /// Matches the Python <c>summarize_for_npc</c> output line-for-line
        /// so the runtime can cross-check what the generator will see.</summary>
        public string SummarizeForNpc(
            string npcId,
            string primaryFactionId = "",
            string secondaryFactionId = "",
            int maxLines = 8)
        {
            var list = ForNpc(npcId, primaryFactionId, secondaryFactionId);
            if (list.Count == 0) return string.Empty;
            if (maxLines > 0 && list.Count > maxLines) list = list.GetRange(0, maxLines);

            var sb = new System.Text.StringBuilder();
            sb.AppendLine(
                "Memory of past encounters with the player (most recent first). " +
                "These are things that actually happened between you and the player " +
                "in prior scenes. Reference them naturally when relevant — do not " +
                "narrate them or mention turn numbers out loud:");
            foreach (var e in list)
            {
                string factionTag = string.IsNullOrEmpty(e.faction_id) ? "" : $", {e.faction_id}";
                sb.AppendLine(
                    $"- [turn {e.turn}, {e.salience}{factionTag}] {e.event_type} — " +
                    $"{(e.summary ?? string.Empty).Trim()}");
            }
            return sb.ToString().TrimEnd();
        }

        // ---------------------------------------------------------------
        // Persistence
        // ---------------------------------------------------------------

        /// <summary>Save to the configured path under persistentDataPath.
        /// JSON layout matches Python's memory.MemoryStore.to_json.</summary>
        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Application.persistentDataPath);
                File.WriteAllText(FullPath, BuildJson());
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgeMemoryStore] save failed: {ex.Message}");
            }
        }

        /// <summary>Load from the configured path. No-op if the file is
        /// absent; logs and clears on parse failure.</summary>
        public void Load()
        {
            if (!File.Exists(FullPath)) return;
            try
            {
                string json = File.ReadAllText(FullPath);
                var dto = JsonUtility.FromJson<Dto>(json);
                if (dto == null)
                {
                    Debug.LogWarning($"[NpcForgeMemoryStore] empty/invalid JSON at {FullPath}");
                    return;
                }
                currentTurn = dto.currentTurn;
                events = dto.events ?? new List<NpcForgeMemoryEvent>();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgeMemoryStore] load failed: {ex.Message}");
            }
        }

        /// <summary>Drop every stored event and reset the turn counter.
        /// Does not auto-save — caller opts in.</summary>
        public void Clear()
        {
            events.Clear();
            currentTurn = 0;
        }

        // ---------------------------------------------------------------
        // JSON helpers — keep byte-compatible with the Python store
        // ---------------------------------------------------------------

        [Serializable]
        private class Dto
        {
            public string schemaVersion = "1";
            public int currentTurn;
            public List<NpcForgeMemoryEvent> events;
        }

        internal string BuildJson()
        {
            var dto = new Dto
            {
                schemaVersion = "1",
                currentTurn = currentTurn,
                events = events,
            };
            return JsonUtility.ToJson(dto, prettyPrint: true);
        }

        // ---------------------------------------------------------------
        // Decay predicate — mirror of _still_salient in Python
        // ---------------------------------------------------------------

        internal static bool StillSalient(NpcForgeMemoryEvent e, int currentTurn)
        {
            switch (e.SalienceEnum)
            {
                case MemorySalience.Pivotal:
                    return true;
                case MemorySalience.Notable:
                    return currentTurn - e.turn <= DecayHorizonNotable;
                default: // trivial
                    return currentTurn - e.turn <= DecayHorizonTrivial;
            }
        }
    }
}
