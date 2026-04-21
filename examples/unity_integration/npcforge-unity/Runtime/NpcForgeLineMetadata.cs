// NpcForgeLineMetadata.cs
//
// Runtime-queryable database of per-line metadata (emotion, intensity,
// duration, npc, source file) derived from npcforge's lines.csv. Game
// code can ask "what emotion was this line generated with?" to drive
// facial animation, camera shake, VO session direction, etc.
//
// Populated at edit time by NpcForgeLinesCsvImporter (Editor assembly)
// or hand-authored if you want a different source of truth.
//
// Why a ScriptableObject and not a runtime CSV parse? Two reasons:
//   1. O(1) lookups after import — a Dictionary keyed by line_id is
//      rebuilt on enable.
//   2. Plays well with AssetBundle / Addressables — the database ships
//      as a single asset reference, not a text file the game has to
//      remember to include in builds.

using System.Collections.Generic;
using UnityEngine;

namespace Altai.NpcForge
{
    /// <summary>Schema-stable row from npcforge's lines.csv.
    /// Column names and order match audio.py._LINES_CSV_FIELDS — keep
    /// in lockstep when one side changes.</summary>
    [System.Serializable]
    public class NpcForgeLineRecord
    {
        [Tooltip("Deterministic <npc_id>_<10-hex> ID — survives regeneration so audio stays bound.")]
        public string lineId;

        public string npcId;
        public string speaker;

        [Tooltip("e.g. 'walk_up:threaten_for_info' | 'bark:greet_patron' | 'greeting:time_of_day=dawn'")]
        public string context;

        [Tooltip("Relative path under out/ — the .yarn file that owns this line.")]
        public string sourceFile;

        [Tooltip("Heuristic emotion: neutral / threatening / pleading / warm / angry / sad / confused / wary / sarcastic.")]
        public string emotion = "neutral";

        [Tooltip("low / medium / high.")]
        public string intensity = "medium";

        [Tooltip("Syllable-based VO budget in seconds.")]
        public float durationSec;

        [TextArea(1, 3)]
        public string text;
    }

    [CreateAssetMenu(fileName = "NpcForgeLineMetadata", menuName = "npcforge/Line Metadata", order = 100)]
    public class NpcForgeLineMetadata : ScriptableObject
    {
        [Tooltip("Every line in the generated dialogue corpus. Populated by " +
                 "NpcForgeLinesCsvImporter when lines.csv is reimported.")]
        [SerializeField] private List<NpcForgeLineRecord> records = new List<NpcForgeLineRecord>();

        // Built on OnEnable so lookups are O(1). Rebuild after manual edits
        // by calling RefreshIndex().
        private Dictionary<string, NpcForgeLineRecord> _byLineId;

        public IReadOnlyList<NpcForgeLineRecord> Records => records;

        /// <summary>Count of distinct NPC ids represented in the corpus.</summary>
        public int DistinctNpcCount
        {
            get
            {
                var seen = new HashSet<string>();
                foreach (var r in records) if (!string.IsNullOrEmpty(r?.npcId)) seen.Add(r.npcId);
                return seen.Count;
            }
        }

        public NpcForgeLineRecord Find(string lineId)
        {
            if (string.IsNullOrEmpty(lineId)) return null;
            EnsureIndex();
            return _byLineId.TryGetValue(lineId, out var rec) ? rec : null;
        }

        public bool Contains(string lineId)
        {
            EnsureIndex();
            return !string.IsNullOrEmpty(lineId) && _byLineId.ContainsKey(lineId);
        }

        /// <summary>Replace the records list wholesale. Called by the CSV
        /// importer; also safe to use from user code.</summary>
        public void SetRecords(IList<NpcForgeLineRecord> newRecords)
        {
            records.Clear();
            if (newRecords != null)
            {
                foreach (var r in newRecords) if (r != null) records.Add(r);
            }
            _byLineId = null; // invalidate
        }

        /// <summary>Rebuild the lookup index. Call after manual edits to
        /// <see cref="records"/> if you need Find to see them immediately.</summary>
        public void RefreshIndex()
        {
            _byLineId = null;
            EnsureIndex();
        }

        private void OnEnable() => _byLineId = null;

        private void EnsureIndex()
        {
            if (_byLineId != null) return;
            _byLineId = new Dictionary<string, NpcForgeLineRecord>(records.Count);
            foreach (var r in records)
            {
                if (r == null || string.IsNullOrEmpty(r.lineId)) continue;
                // Last-one-wins on collision — matches lines.csv's own
                // last-column-wins semantics for rare dup ids.
                _byLineId[r.lineId] = r;
            }
        }

        // -------------------------------------------------------------
        // Query helpers — small conveniences for gameplay code
        // -------------------------------------------------------------

        public IEnumerable<NpcForgeLineRecord> LinesFor(string npcId)
        {
            if (string.IsNullOrEmpty(npcId)) yield break;
            foreach (var r in records)
            {
                if (r != null && r.npcId == npcId) yield return r;
            }
        }

        public IEnumerable<NpcForgeLineRecord> LinesByEmotion(string emotion)
        {
            if (string.IsNullOrEmpty(emotion)) yield break;
            foreach (var r in records)
            {
                if (r != null && r.emotion == emotion) yield return r;
            }
        }
    }
}
