// NpcForgeDialoguePreviewWindow.cs
//
// In-Editor preview of generated .yarn files. Parses the file with
// NpcForgeYarnParser and renders each node according to its detected
// kind (walk-up / bark / enum greeting / repeat greeting). No Play mode
// required — writers can iterate on character voice without booting the
// scene.
//
// Why not use Yarn Spinner's own previewer? As of Yarn Spinner for
// Unity 2.4, there isn't one — you have to Play the scene and walk up
// to the NPC. This window exists specifically for that gap.

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public class NpcForgeDialoguePreviewWindow : EditorWindow
    {
        private const string DialogueRoot = "Assets/NpcForge/Dialogue";

        private List<string> _yarnFiles = new List<string>();
        private int _selectedFileIndex = -1;
        private List<YarnNode> _parsedNodes = new List<YarnNode>();
        private int _selectedNodeIndex;
        private Vector2 _listScroll;
        private Vector2 _nodeScroll;
        private string _searchFilter = string.Empty;

        [MenuItem("Tools/npcforge/Dialogue Preview...", priority = 22)]
        public static void Open()
        {
            var wnd = GetWindow<NpcForgeDialoguePreviewWindow>();
            wnd.titleContent = new GUIContent("npcforge Preview");
            wnd.minSize = new Vector2(720, 480);
            wnd.Refresh();
            wnd.Show();
        }

        private void OnFocus() => Refresh();

        private void Refresh()
        {
            _yarnFiles.Clear();
            if (Directory.Exists(DialogueRoot))
            {
                foreach (string p in Directory.GetFiles(DialogueRoot, "*.yarn", SearchOption.AllDirectories))
                {
                    _yarnFiles.Add(p.Replace('\\', '/'));
                }
                _yarnFiles.Sort();
            }
            if (_selectedFileIndex >= _yarnFiles.Count) _selectedFileIndex = -1;
            if (_selectedFileIndex == -1 && _yarnFiles.Count > 0)
            {
                _selectedFileIndex = 0;
            }
            ReloadSelection();
        }

        private void ReloadSelection()
        {
            _parsedNodes.Clear();
            _selectedNodeIndex = 0;
            if (_selectedFileIndex < 0 || _selectedFileIndex >= _yarnFiles.Count) return;

            string path = _yarnFiles[_selectedFileIndex];
            try
            {
                string text = File.ReadAllText(path);
                _parsedNodes = NpcForgeYarnParser.Parse(text);
            }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[NpcForge Preview] Failed to parse {path}: {ex.Message}");
            }
        }

        private void OnGUI()
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                DrawFileList();
                DrawDetailPane();
            }
        }

        private void DrawFileList()
        {
            using (new EditorGUILayout.VerticalScope(GUILayout.Width(260)))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    EditorGUILayout.LabelField(
                        $"Dialogue files ({_yarnFiles.Count})",
                        EditorStyles.boldLabel);
                    if (GUILayout.Button("Refresh", EditorStyles.miniButton, GUILayout.Width(64)))
                        Refresh();
                }

                _searchFilter = EditorGUILayout.TextField(_searchFilter, EditorStyles.toolbarSearchField);

                _listScroll = EditorGUILayout.BeginScrollView(_listScroll);
                for (int i = 0; i < _yarnFiles.Count; i++)
                {
                    string path = _yarnFiles[i];
                    string name = Path.GetFileName(path);
                    if (!string.IsNullOrEmpty(_searchFilter)
                        && name.IndexOf(_searchFilter, System.StringComparison.OrdinalIgnoreCase) < 0)
                        continue;

                    var style = (i == _selectedFileIndex)
                        ? EditorStyles.boldLabel
                        : EditorStyles.label;
                    if (GUILayout.Button(name, style, GUILayout.Height(18)))
                    {
                        _selectedFileIndex = i;
                        ReloadSelection();
                    }
                }
                EditorGUILayout.EndScrollView();

                if (_yarnFiles.Count == 0)
                {
                    EditorGUILayout.HelpBox(
                        "No .yarn files under Assets/NpcForge/Dialogue/. " +
                        "Run engine-sync from Tools → npcforge → Open Panel…",
                        MessageType.Info);
                }
            }
        }

        private void DrawDetailPane()
        {
            using (new EditorGUILayout.VerticalScope())
            {
                if (_selectedFileIndex < 0 || _selectedFileIndex >= _yarnFiles.Count)
                {
                    EditorGUILayout.LabelField("(pick a file on the left)",
                        EditorStyles.centeredGreyMiniLabel);
                    return;
                }

                string path = _yarnFiles[_selectedFileIndex];
                EditorGUILayout.LabelField(path, EditorStyles.miniLabel);

                if (_parsedNodes.Count == 0)
                {
                    EditorGUILayout.HelpBox("File parsed to zero nodes.", MessageType.Warning);
                    return;
                }

                // Node picker (most files have one node, but world.yarn + walk-ups do have multiples).
                DrawNodeTabs();

                YarnNode node = _parsedNodes[_selectedNodeIndex];
                EditorGUILayout.Space(4);
                DrawNodeHeader(node);

                _nodeScroll = EditorGUILayout.BeginScrollView(_nodeScroll);
                switch (node.DetectKind())
                {
                    case YarnNode.Kind.WalkUp: DrawWalkUp(node); break;
                    case YarnNode.Kind.Bark: DrawBarks(node); break;
                    case YarnNode.Kind.EnumGreeting: DrawEnum(node); break;
                    case YarnNode.Kind.RepeatGreeting: DrawVisits(node); break;
                    case YarnNode.Kind.WorldStart: DrawPreambleOnly(node, "World start node"); break;
                    default: DrawPreambleOnly(node, "Node"); break;
                }
                EditorGUILayout.EndScrollView();
            }
        }

        private void DrawNodeTabs()
        {
            if (_parsedNodes.Count <= 1) return;
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                for (int i = 0; i < _parsedNodes.Count; i++)
                {
                    if (GUILayout.Toggle(i == _selectedNodeIndex, _parsedNodes[i].Title,
                            EditorStyles.toolbarButton))
                    {
                        if (i != _selectedNodeIndex) _selectedNodeIndex = i;
                    }
                }
            }
        }

        private void DrawNodeHeader(YarnNode node)
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField(node.Title, EditorStyles.boldLabel);
                GUILayout.FlexibleSpace();
                EditorGUILayout.LabelField(
                    $"[{node.DetectKind()}]",
                    EditorStyles.miniLabel,
                    GUILayout.Width(130));
            }
            if (node.Tags.Count > 0)
            {
                EditorGUILayout.LabelField("tags: " + string.Join(", ", node.Tags),
                    EditorStyles.miniLabel);
            }
        }

        // ---------------------------------------------------------------
        // Per-kind renderers — line formatting matches play.py's colours
        // as close as IMGUI permits (player = yellow, NPC = cyan-ish).
        // ---------------------------------------------------------------

        private static readonly Color _playerColor = new Color(0.95f, 0.8f, 0.3f);
        private static readonly Color _npcColor = new Color(0.4f, 0.85f, 0.95f);
        private static readonly Color _labelColor = new Color(0.9f, 0.6f, 0.95f);
        private static readonly Color _dimColor = new Color(0.65f, 0.65f, 0.65f);

        private void DrawWalkUp(YarnNode node)
        {
            foreach (var line in node.Preamble) DrawLine(line);
            foreach (var opt in node.Options)
            {
                EditorGUILayout.Space(6);
                using (ColorScope(_labelColor))
                    EditorGUILayout.LabelField($"— [{opt.Label}] —", EditorStyles.boldLabel);
                foreach (var line in opt.Lines) DrawLine(line);
                if (!string.IsNullOrEmpty(opt.JumpTo))
                {
                    using (ColorScope(_dimColor))
                        EditorGUILayout.LabelField($"  (jump to {opt.JumpTo})",
                            EditorStyles.miniLabel);
                }
            }
        }

        private void DrawBarks(YarnNode node)
        {
            EditorGUILayout.LabelField(
                $"Bark rotation — {node.BarkVariants.Count} variants",
                EditorStyles.boldLabel);
            EditorGUILayout.Space(4);
            for (int i = 0; i < node.BarkVariants.Count; i++)
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    using (ColorScope(_dimColor))
                        EditorGUILayout.LabelField($"{i + 1,2}.",
                            GUILayout.Width(30));
                    DrawLine(node.BarkVariants[i]);
                }
            }
        }

        private void DrawEnum(YarnNode node)
        {
            EditorGUILayout.LabelField(
                $"Enum-keyed greeting — {node.EnumVariants.Count} variants",
                EditorStyles.boldLabel);
            EditorGUILayout.Space(4);
            foreach (var v in node.EnumVariants)
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    using (ColorScope(_labelColor))
                        EditorGUILayout.LabelField($"[{v.Variable}={v.Value}]",
                            EditorStyles.boldLabel,
                            GUILayout.Width(220));
                    DrawLine(v.Line);
                }
            }
        }

        private void DrawVisits(YarnNode node)
        {
            EditorGUILayout.LabelField(
                $"Repeat-greeting — {node.VisitVariants.Count} branches",
                EditorStyles.boldLabel);
            EditorGUILayout.Space(4);
            foreach (var v in node.VisitVariants)
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    string tag = v.VisitIndex == -1 ? "visit else" : $"visit #{v.VisitIndex}";
                    using (ColorScope(_labelColor))
                        EditorGUILayout.LabelField($"[{tag}]",
                            EditorStyles.boldLabel,
                            GUILayout.Width(120));
                    DrawLine(v.Line);
                }
            }
        }

        private void DrawPreambleOnly(YarnNode node, string title)
        {
            EditorGUILayout.LabelField(title, EditorStyles.boldLabel);
            foreach (var line in node.Preamble) DrawLine(line);
        }

        // ---------------------------------------------------------------
        // Shared line rendering
        // ---------------------------------------------------------------

        private void DrawLine(YarnLine line)
        {
            if (line == null || string.IsNullOrEmpty(line.Text)) return;
            using (new EditorGUILayout.HorizontalScope())
            {
                if (string.IsNullOrEmpty(line.Speaker))
                {
                    EditorGUILayout.LabelField(line.Text, EditorStyles.wordWrappedLabel);
                }
                else
                {
                    bool isPlayer = line.Speaker.Trim().Equals("Player",
                        System.StringComparison.OrdinalIgnoreCase);
                    using (ColorScope(isPlayer ? _playerColor : _npcColor))
                    {
                        EditorGUILayout.LabelField(line.Speaker + ":",
                            EditorStyles.boldLabel,
                            GUILayout.Width(120));
                    }
                    EditorGUILayout.LabelField(line.Text, EditorStyles.wordWrappedLabel);
                }
            }
        }

        private static System.IDisposable ColorScope(Color c)
        {
            return new ContentColorScope(c);
        }

        private sealed class ContentColorScope : System.IDisposable
        {
            private readonly Color _previous;
            public ContentColorScope(Color next)
            {
                _previous = GUI.contentColor;
                GUI.contentColor = next;
            }
            public void Dispose() { GUI.contentColor = _previous; }
        }
    }
}
