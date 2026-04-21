// NpcForgeAudioMap.cs
//
// Maps npcforge-generated line_ids to Unity AudioClips. Populated in
// the Editor (hand-drag or bulk-assign via NpcForgeAudioMapInspector),
// queried at runtime by NpcForgeAudioDialogueView.
//
// Shape choice: a List of Entry structs rather than a Dictionary,
// because Unity can't serialise generic Dictionaries without custom
// surrogate code. An O(1) index is built on OnEnable so runtime
// lookups stay cheap.
//
// Coverage reporting: .Coverage(metadata) tells designers at a glance
// how many line_ids in the metadata asset have matching audio — useful
// in the custom inspector and in CI checks.

using System.Collections.Generic;
using UnityEngine;

namespace Altai.NpcForge
{
    [CreateAssetMenu(fileName = "NpcForgeAudioMap", menuName = "npcforge/Audio Map", order = 101)]
    public class NpcForgeAudioMap : ScriptableObject
    {
        [System.Serializable]
        public class Entry
        {
            [Tooltip("npcforge line_id — the deterministic <npc_id>_<10-hex> key from lines.csv.")]
            public string lineId;

            [Tooltip("AudioClip to play when a DialogueRunner delivers this line.")]
            public AudioClip clip;

            [Tooltip("Optional — per-line volume override (0..1). Leave at 1 to use the AudioSource default.")]
            [Range(0f, 1f)] public float volume = 1f;
        }

        [SerializeField] private List<Entry> entries = new List<Entry>();

        public IReadOnlyList<Entry> Entries => entries;

        private Dictionary<string, Entry> _byLineId;

        private void OnEnable() => _byLineId = null;

        /// <summary>Look up the clip for a line_id. Returns null if no clip
        /// is mapped or the lineId is empty.</summary>
        public AudioClip GetClip(string lineId)
        {
            var e = GetEntry(lineId);
            return e?.clip;
        }

        public Entry GetEntry(string lineId)
        {
            if (string.IsNullOrEmpty(lineId)) return null;
            EnsureIndex();
            return _byLineId.TryGetValue(lineId, out var e) ? e : null;
        }

        /// <summary>Set (or replace) the clip for a given line_id. No-ops
        /// for empty/null ids. Rebuilds the index lazily.</summary>
        public void SetClip(string lineId, AudioClip clip, float volume = 1f)
        {
            if (string.IsNullOrEmpty(lineId)) return;
            var existing = GetEntry(lineId);
            if (existing != null)
            {
                existing.clip = clip;
                existing.volume = volume;
            }
            else
            {
                entries.Add(new Entry { lineId = lineId, clip = clip, volume = volume });
            }
            _byLineId = null;
        }

        public void Remove(string lineId)
        {
            if (string.IsNullOrEmpty(lineId)) return;
            entries.RemoveAll(e => e != null && e.lineId == lineId);
            _byLineId = null;
        }

        /// <summary>Describes how many line_ids in <paramref name="metadata"/>
        /// have a clip assigned in this map. Useful for coverage displays.</summary>
        public CoverageStats Coverage(NpcForgeLineMetadata metadata)
        {
            var stats = new CoverageStats();
            if (metadata == null) return stats;
            foreach (var rec in metadata.Records)
            {
                if (rec == null || string.IsNullOrEmpty(rec.lineId)) continue;
                stats.Total++;
                var entry = GetEntry(rec.lineId);
                if (entry != null && entry.clip != null) stats.Assigned++;
            }
            return stats;
        }

        public struct CoverageStats
        {
            public int Total;
            public int Assigned;
            public int Missing => Total - Assigned;
            public float Percent => Total == 0 ? 0f : (Assigned / (float)Total);
        }

        private void EnsureIndex()
        {
            if (_byLineId != null) return;
            _byLineId = new Dictionary<string, Entry>(entries.Count);
            foreach (var e in entries)
            {
                if (e == null || string.IsNullOrEmpty(e.lineId)) continue;
                _byLineId[e.lineId] = e;
            }
        }
    }
}
