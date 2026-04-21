// NpcForgeAudioMapInspector.cs
//
// Custom inspector for NpcForgeAudioMap that's productive to actually
// work with on a big project:
//
//   - Coverage bar: "127 / 183 lines have audio" + percent.
//   - Filter by npc_id or emotion using the paired metadata asset.
//   - Bulk-assign from a folder of AudioClips named <line_id>.<ext>.
//   - Clear entries with missing clips.
//
// Keep a NpcForgeLineMetadata assigned to drive coverage calculations
// and filtering; the map still works without one, just without stats.

using System.IO;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    [CustomEditor(typeof(NpcForgeAudioMap))]
    public class NpcForgeAudioMapInspector : UnityEditor.Editor
    {
        private NpcForgeLineMetadata _metadata;
        private string _filterNpc = string.Empty;
        private string _filterEmotion = string.Empty;
        private bool _hideAssigned;

        private static readonly string[] _emotions =
        {
            "(any)", "neutral", "threatening", "pleading", "warm",
            "angry", "sad", "confused", "wary", "sarcastic",
        };

        public override void OnInspectorGUI()
        {
            var map = (NpcForgeAudioMap)target;

            EditorGUILayout.LabelField("Metadata + coverage", EditorStyles.boldLabel);
            _metadata = (NpcForgeLineMetadata)EditorGUILayout.ObjectField(
                new GUIContent("Line metadata",
                    "Paired NpcForgeLineMetadata — drives coverage stats + filters."),
                _metadata, typeof(NpcForgeLineMetadata), false);

            if (_metadata == null)
            {
                // Try to auto-find a NpcForgeLineMetadata in the project —
                // most users have exactly one, living next to lines.csv.
                var guids = AssetDatabase.FindAssets("t:NpcForgeLineMetadata");
                if (guids.Length == 1)
                {
                    _metadata = AssetDatabase.LoadAssetAtPath<NpcForgeLineMetadata>(
                        AssetDatabase.GUIDToAssetPath(guids[0]));
                }
            }

            if (_metadata != null)
            {
                var stats = map.Coverage(_metadata);
                var rect = GUILayoutUtility.GetRect(0, 18f, GUILayout.ExpandWidth(true));
                EditorGUI.ProgressBar(rect, stats.Percent,
                    $"{stats.Assigned} / {stats.Total} assigned ({stats.Percent * 100f:0.0}%), {stats.Missing} missing");
            }
            else
            {
                EditorGUILayout.HelpBox(
                    "Assign a NpcForgeLineMetadata to see coverage stats.",
                    MessageType.Info);
            }

            EditorGUILayout.Space(6);
            DrawBulkAssign(map);

            EditorGUILayout.Space(10);
            DrawFilter();

            EditorGUILayout.Space(6);
            DrawEntriesList(map);

            serializedObject.ApplyModifiedProperties();
        }

        private void DrawBulkAssign(NpcForgeAudioMap map)
        {
            EditorGUILayout.LabelField("Bulk assign from folder", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "Pick a folder of AudioClips named like <line_id>.wav / .mp3 / .ogg. " +
                "Each clip auto-binds to the matching line_id. Existing " +
                "entries with assigned clips are not overwritten.",
                MessageType.None);

            if (GUILayout.Button("Pick folder & assign..."))
            {
                string picked = EditorUtility.OpenFolderPanel(
                    "Select folder of AudioClips", Application.dataPath, "");
                if (!string.IsNullOrEmpty(picked))
                {
                    int added = BulkAssignFromFolder(map, picked);
                    Debug.Log($"[NpcForgeAudio] Bulk-assigned {added} clip(s) from {picked}.");
                }
            }

            if (GUILayout.Button("Remove entries whose clip is missing"))
            {
                int removed = 0;
                var entries = map.Entries;
                for (int i = entries.Count - 1; i >= 0; i--)
                {
                    var e = entries[i];
                    if (e != null && e.clip == null)
                    {
                        map.Remove(e.lineId);
                        removed++;
                    }
                }
                EditorUtility.SetDirty(map);
                Debug.Log($"[NpcForgeAudio] Removed {removed} empty entries.");
            }
        }

        private int BulkAssignFromFolder(NpcForgeAudioMap map, string absFolder)
        {
            // Convert absolute path to project-relative ("Assets/...") so
            // we can LoadAssetAtPath. Skip anything outside the project.
            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            if (!absFolder.StartsWith(projectRoot))
            {
                Debug.LogWarning($"[NpcForgeAudio] Folder must be inside the Unity project: {absFolder}");
                return 0;
            }
            string rel = "Assets" + absFolder.Substring(Application.dataPath.Length);
            int added = 0;

            var guids = AssetDatabase.FindAssets("t:AudioClip", new[] { rel });
            foreach (string guid in guids)
            {
                string p = AssetDatabase.GUIDToAssetPath(guid);
                var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(p);
                if (clip == null) continue;
                string lineId = Path.GetFileNameWithoutExtension(p);
                // Don't overwrite an existing assigned clip unless the
                // user asks. We're conservative to avoid surprise churn.
                var existing = map.GetEntry(lineId);
                if (existing != null && existing.clip != null) continue;
                map.SetClip(lineId, clip, volume: 1f);
                added++;
            }
            EditorUtility.SetDirty(map);
            return added;
        }

        private void DrawFilter()
        {
            EditorGUILayout.LabelField("Filter entries", EditorStyles.boldLabel);
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField("NPC id", GUILayout.Width(60));
                _filterNpc = EditorGUILayout.TextField(_filterNpc);
            }
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField("Emotion", GUILayout.Width(60));
                int idx = System.Array.IndexOf(_emotions, string.IsNullOrEmpty(_filterEmotion) ? "(any)" : _filterEmotion);
                if (idx < 0) idx = 0;
                int newIdx = EditorGUILayout.Popup(idx, _emotions);
                _filterEmotion = newIdx == 0 ? string.Empty : _emotions[newIdx];
            }
            _hideAssigned = EditorGUILayout.ToggleLeft(
                new GUIContent("Hide already-assigned entries",
                    "Focus on what's still missing."),
                _hideAssigned);
        }

        private void DrawEntriesList(NpcForgeAudioMap map)
        {
            EditorGUILayout.LabelField($"Entries ({map.Entries.Count})", EditorStyles.boldLabel);

            // Pull each entry's metadata for filter matching.
            int shown = 0;
            for (int i = 0; i < map.Entries.Count; i++)
            {
                var e = map.Entries[i];
                if (e == null) continue;
                if (_hideAssigned && e.clip != null) continue;

                NpcForgeLineRecord meta = _metadata != null ? _metadata.Find(e.lineId) : null;
                if (!string.IsNullOrEmpty(_filterNpc) && meta != null
                    && (meta.npcId ?? "").IndexOf(_filterNpc, System.StringComparison.OrdinalIgnoreCase) < 0) continue;
                if (!string.IsNullOrEmpty(_filterEmotion) && meta != null
                    && !string.Equals(meta.emotion, _filterEmotion, System.StringComparison.OrdinalIgnoreCase)) continue;

                DrawEntryRow(map, e, meta);
                shown++;
                if (shown >= 200) break; // cap for IMGUI sanity
            }

            if (shown == 0)
            {
                EditorGUILayout.LabelField("(no entries match the current filter)",
                    EditorStyles.centeredGreyMiniLabel);
            }
        }

        private static void DrawEntryRow(NpcForgeAudioMap map, NpcForgeAudioMap.Entry e, NpcForgeLineRecord meta)
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.helpBox))
            {
                using (new EditorGUILayout.VerticalScope())
                {
                    EditorGUILayout.LabelField(e.lineId, EditorStyles.miniBoldLabel);
                    if (meta != null)
                    {
                        EditorGUILayout.LabelField(
                            $"{meta.npcId} / {meta.context} / {meta.emotion}:{meta.intensity} / {meta.durationSec:0.0}s",
                            EditorStyles.miniLabel);
                        if (!string.IsNullOrEmpty(meta.text))
                        {
                            EditorGUILayout.LabelField($"\"{meta.text}\"",
                                EditorStyles.wordWrappedMiniLabel);
                        }
                    }
                }
                using (new EditorGUILayout.VerticalScope(GUILayout.Width(240)))
                {
                    var picked = (AudioClip)EditorGUILayout.ObjectField(
                        e.clip, typeof(AudioClip), false);
                    if (picked != e.clip)
                    {
                        e.clip = picked;
                        EditorUtility.SetDirty(map);
                    }
                    e.volume = EditorGUILayout.Slider("vol", e.volume, 0f, 1f);
                }
            }
        }
    }
}
