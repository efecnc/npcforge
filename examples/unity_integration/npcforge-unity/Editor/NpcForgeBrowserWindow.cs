// NpcForgeBrowserWindow.cs
//
// Browse every NPC in the configured project directory — their voice,
// relationships, knowledge gates, allowed intents, forbidden words, and
// state evolution — without leaving the Editor. Reads the project's
// characters.yaml directly; no LLM calls.
//
// Scope intentionally narrow: read-only. Editing happens in your text
// editor or the npcforge panel; this window is for reference and
// auditing.

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public class NpcForgeBrowserWindow : EditorWindow
    {
        private Vector2 _listScroll;
        private Vector2 _detailScroll;
        private string _selectedId;
        private List<NpcSummary> _npcs = new List<NpcSummary>();
        private string _searchFilter = string.Empty;
        private string _lastLoadedPath = string.Empty;

        [MenuItem("Tools/npcforge/NPC Browser...", priority = 20)]
        public static void Open()
        {
            var wnd = GetWindow<NpcForgeBrowserWindow>();
            wnd.titleContent = new GUIContent("NPCs");
            wnd.minSize = new Vector2(720, 460);
            wnd.Reload();
            wnd.Show();
        }

        private void OnFocus() { Reload(); }

        private void Reload()
        {
            _npcs = NpcForgeYamlReader.LoadSummaries(NpcForgePreferences.DemoDir);
            _lastLoadedPath = NpcForgePreferences.DemoDir;
            if (_selectedId != null && _npcs.FindIndex(n => n.Id == _selectedId) < 0 && _npcs.Count > 0)
            {
                _selectedId = _npcs[0].Id;
            }
            Repaint();
        }

        private void OnGUI()
        {
            DrawToolbar();

            using (new EditorGUILayout.HorizontalScope())
            {
                DrawList();
                EditorGUILayout.Space(4);
                DrawDetail();
            }
        }

        private void DrawToolbar()
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                if (GUILayout.Button("Reload", EditorStyles.toolbarButton, GUILayout.Width(70)))
                {
                    Reload();
                }
                GUILayout.Space(6);
                GUILayout.Label("Project:", GUILayout.Width(56));
                EditorGUILayout.LabelField(_lastLoadedPath, EditorStyles.miniLabel);
                GUILayout.FlexibleSpace();
                GUILayout.Label($"{_npcs.Count} NPC{(_npcs.Count == 1 ? "" : "s")}",
                    EditorStyles.miniLabel, GUILayout.Width(80));
            }

            using (new EditorGUILayout.HorizontalScope())
            {
                GUILayout.Label("Filter:", GUILayout.Width(44));
                _searchFilter = EditorGUILayout.TextField(_searchFilter ?? string.Empty);
            }
        }

        private void DrawList()
        {
            using (new EditorGUILayout.VerticalScope(GUILayout.Width(240)))
            {
                EditorGUILayout.LabelField("Cast", EditorStyles.boldLabel);
                _listScroll = EditorGUILayout.BeginScrollView(_listScroll);
                string f = (_searchFilter ?? string.Empty).Trim().ToLowerInvariant();
                foreach (var npc in _npcs)
                {
                    if (f.Length > 0 && !npc.Matches(f)) continue;
                    bool active = npc.Id == _selectedId;
                    var prev = GUI.backgroundColor;
                    if (active) GUI.backgroundColor = new Color(0.3f, 0.55f, 0.9f, 1f);
                    string label = $"{npc.Name}\n  {npc.Role}";
                    if (GUILayout.Button(label, GUILayout.Height(40)))
                    {
                        _selectedId = npc.Id;
                    }
                    GUI.backgroundColor = prev;
                }
                EditorGUILayout.EndScrollView();
            }
        }

        private void DrawDetail()
        {
            using (new EditorGUILayout.VerticalScope())
            {
                EditorGUILayout.LabelField("Details", EditorStyles.boldLabel);
                _detailScroll = EditorGUILayout.BeginScrollView(_detailScroll, GUILayout.ExpandHeight(true));
                var sel = _npcs.Find(n => n.Id == _selectedId);
                if (sel == null)
                {
                    EditorGUILayout.HelpBox(
                        "No NPC selected. If the list is empty, open the npcforge panel " +
                        "and set your project directory first.",
                        MessageType.Info);
                }
                else
                {
                    DrawNpcDetail(sel);
                }
                EditorGUILayout.EndScrollView();
            }
        }

        private void DrawNpcDetail(NpcSummary npc)
        {
            using (new EditorGUILayout.VerticalScope("HelpBox"))
            {
                EditorGUILayout.LabelField(npc.Name, EditorStyles.boldLabel);
                EditorGUILayout.LabelField(npc.Role, EditorStyles.miniLabel);
            }
            EditorGUILayout.Space(4);

            Field("Voice", npc.Voice);
            Field("Background", npc.Background);
            Field("Vocabulary ceiling", npc.VocabularyCeiling);

            if (!string.IsNullOrEmpty(npc.Secret))
            {
                EditorGUILayout.Space(2);
                EditorGUILayout.LabelField("Secret (never disclose directly)", EditorStyles.miniBoldLabel);
                EditorGUILayout.SelectableLabel(npc.Secret,
                    EditorStyles.wordWrappedLabel,
                    GUILayout.Height(32));
            }

            DrawList("Motivations", npc.Motivations);
            DrawList("Speech quirks", npc.SpeechQuirks);
            DrawList("Sample lines", npc.SampleLines);
            DrawList("Forbidden words", npc.ForbiddenWords);
            DrawList("Accent markers", npc.AccentMarkers);
            DrawList("Allowed intents", npc.AllowedIntents);
            DrawList("Reacts to (state)", npc.ReactsTo);

            if (npc.Relationships.Count > 0)
            {
                EditorGUILayout.Space(4);
                EditorGUILayout.LabelField("Relationships", EditorStyles.miniBoldLabel);
                foreach (var rel in npc.Relationships)
                {
                    using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
                    {
                        EditorGUILayout.LabelField($"→ {rel.Key}", EditorStyles.boldLabel);
                        EditorGUILayout.SelectableLabel(rel.Value,
                            EditorStyles.wordWrappedLabel,
                            GUILayout.Height(28));
                    }
                }
            }

            if (npc.Knowledge.Count > 0)
            {
                EditorGUILayout.Space(4);
                EditorGUILayout.LabelField("Knowledge (gated reveals)", EditorStyles.miniBoldLabel);
                foreach (var k in npc.Knowledge)
                {
                    using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
                    {
                        EditorGUILayout.LabelField(k.Key, EditorStyles.boldLabel);
                        EditorGUILayout.SelectableLabel(k.Value,
                            EditorStyles.wordWrappedLabel,
                            GUILayout.Height(48));
                    }
                }
            }

            if (npc.StateEvolution.Count > 0)
            {
                EditorGUILayout.Space(4);
                EditorGUILayout.LabelField("State evolution", EditorStyles.miniBoldLabel);
                foreach (var s in npc.StateEvolution)
                {
                    using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
                    {
                        EditorGUILayout.LabelField($"when {s.Key}", EditorStyles.boldLabel);
                        EditorGUILayout.SelectableLabel(s.Value,
                            EditorStyles.wordWrappedLabel,
                            GUILayout.Height(32));
                    }
                }
            }
        }

        private static void Field(string label, string value)
        {
            if (string.IsNullOrEmpty(value)) return;
            EditorGUILayout.Space(2);
            EditorGUILayout.LabelField(label, EditorStyles.miniBoldLabel);
            EditorGUILayout.SelectableLabel(value,
                EditorStyles.wordWrappedLabel,
                GUILayout.Height(32));
        }

        private static void DrawList(string label, List<string> items)
        {
            if (items == null || items.Count == 0) return;
            EditorGUILayout.Space(2);
            EditorGUILayout.LabelField(label, EditorStyles.miniBoldLabel);
            foreach (string item in items)
            {
                EditorGUILayout.LabelField("• " + item, EditorStyles.wordWrappedLabel);
            }
        }
    }
}
