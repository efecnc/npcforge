// NpcForgeWindow.cs
//
// EditorWindow surface for driving npcforge from inside Unity. Three
// sections: settings (paths, API key), generation (build / gen-* / sync),
// and a scrolling log that streams CLI output.
//
// UI Toolkit (UIElements) is the recommended Unity 2022+ pattern, but
// we stick to IMGUI here so the package has zero extra package
// dependencies. A UI Toolkit rewrite can slot in later.

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public class NpcForgeWindow : EditorWindow
    {
        private Vector2 _logScroll;
        private readonly List<string> _logLines = new List<string>(256);
        private bool _running;
        private string _runningLabel = string.Empty;

        [MenuItem("Tools/npcforge/Open Panel...", priority = 100)]
        public static void Open()
        {
            var wnd = GetWindow<NpcForgeWindow>();
            wnd.titleContent = new GUIContent("npcforge");
            wnd.minSize = new Vector2(420, 520);
            wnd.Show();
        }

        private void OnGUI()
        {
            EditorGUILayout.Space(6);
            DrawSettingsSection();
            EditorGUILayout.Space(10);
            DrawGenerationSection();
            EditorGUILayout.Space(10);
            DrawSyncSection();
            EditorGUILayout.Space(10);
            DrawLogSection();
        }

        // ---------------------------------------------------------------
        // Settings
        // ---------------------------------------------------------------

        private void DrawSettingsSection()
        {
            EditorGUILayout.LabelField("Settings", EditorStyles.boldLabel);
            using (new EditorGUI.IndentLevelScope())
            {
                NpcForgePreferences.NpcforgePath = EditorGUILayout.TextField(
                    new GUIContent("npcforge binary",
                        "Absolute path to the npcforge CLI, or 'npcforge' if on PATH."),
                    NpcForgePreferences.NpcforgePath);

                using (new EditorGUILayout.HorizontalScope())
                {
                    NpcForgePreferences.DemoDir = EditorGUILayout.TextField(
                        new GUIContent("Project directory",
                            "Directory that holds characters.yaml, variables.yaml, lore/."),
                        NpcForgePreferences.DemoDir);
                    if (GUILayout.Button("Browse", GUILayout.Width(70)))
                    {
                        string picked = EditorUtility.OpenFolderPanel(
                            "Select npcforge project directory",
                            NpcForgePreferences.DemoDir, string.Empty);
                        if (!string.IsNullOrEmpty(picked))
                        {
                            NpcForgePreferences.DemoDir = picked;
                        }
                    }
                }

                NpcForgePreferences.GeminiApiKey = EditorGUILayout.PasswordField(
                    new GUIContent("GEMINI_API_KEY",
                        "Passed as an env var to every CLI call. Stored in EditorPrefs only, not in the project."),
                    NpcForgePreferences.GeminiApiKey);

                NpcForgePreferences.InstallScriptsOnFirstSync = EditorGUILayout.Toggle(
                    new GUIContent("Install runtime scripts on first sync",
                        "Only relevant for engine-sync; Unity skips existing files so this is safe to leave on."),
                    NpcForgePreferences.InstallScriptsOnFirstSync);
            }
        }

        // ---------------------------------------------------------------
        // Generation
        // ---------------------------------------------------------------

        private void DrawGenerationSection()
        {
            EditorGUILayout.LabelField("Generate", EditorStyles.boldLabel);
            using (new EditorGUI.DisabledScope(_running || !ValidateReady()))
            using (new EditorGUI.IndentLevelScope())
            {
                if (GUILayout.Button(new GUIContent(
                        "World Profile (infer from lore)",
                        "Runs 'npcforge world infer'.")))
                {
                    RunCli("world infer", "--demo-dir", NpcForgePreferences.DemoDir);
                }
                if (GUILayout.Button(new GUIContent(
                        "Generate NPCs (5)",
                        "Runs 'npcforge gen npcs --n 5'. Appends to characters.yaml.")))
                {
                    RunCli("gen npcs", "--demo-dir", NpcForgePreferences.DemoDir, "--n", "5");
                }
                if (GUILayout.Button(new GUIContent(
                        "Build All (walk-up + barks + lines.csv)",
                        "Runs 'npcforge build --mode all'.")))
                {
                    RunCli("build", "--demo-dir", NpcForgePreferences.DemoDir, "--mode", "all");
                }
                if (GUILayout.Button(new GUIContent(
                        "Generate time-of-day greetings",
                        "Runs 'npcforge gen greetings' for every NPC that reacts to time_of_day.")))
                {
                    RunCli("gen greetings", "--demo-dir", NpcForgePreferences.DemoDir);
                }
                if (GUILayout.Button(new GUIContent(
                        "Generate repeat-greetings (n=3)",
                        "Runs 'npcforge gen repeat-greeting --n 3'.")))
                {
                    RunCli("gen repeat-greeting", "--demo-dir", NpcForgePreferences.DemoDir, "--n", "3");
                }
            }
        }

        // ---------------------------------------------------------------
        // Sync
        // ---------------------------------------------------------------

        private void DrawSyncSection()
        {
            EditorGUILayout.LabelField("Sync into this Unity project", EditorStyles.boldLabel);
            using (new EditorGUI.DisabledScope(_running || !ValidateReady()))
            using (new EditorGUI.IndentLevelScope())
            {
                EditorGUILayout.HelpBox(
                    "Copies the npcforge out/ folder into Assets/NpcForge/Dialogue/ " +
                    "(and Scripts/ when 'install scripts' is on). Yarn Spinner generates " +
                    ".meta files automatically on first reimport.",
                    MessageType.Info);

                if (GUILayout.Button("Sync now (to this Unity project)"))
                {
                    string projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
                    if (string.IsNullOrEmpty(projectRoot))
                    {
                        LogLine("[NpcForge] ERROR: could not resolve Unity project root.");
                        return;
                    }

                    var args = new List<string>
                    {
                        "engine-sync",
                        "--engine", "unity",
                        "--demo-dir", NpcForgePreferences.DemoDir,
                        "--project-dir", projectRoot,
                    };
                    if (NpcForgePreferences.InstallScriptsOnFirstSync)
                    {
                        args.Add("--install-scripts");
                    }
                    RunCli(args.ToArray());
                }

                if (GUILayout.Button("Dry-run sync"))
                {
                    string projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
                    RunCli("engine-sync",
                        "--engine", "unity",
                        "--demo-dir", NpcForgePreferences.DemoDir,
                        "--project-dir", projectRoot,
                        "--dry-run",
                        "--verbose");
                }
            }
        }

        // ---------------------------------------------------------------
        // Log
        // ---------------------------------------------------------------

        private void DrawLogSection()
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField("Log", EditorStyles.boldLabel);
                GUILayout.FlexibleSpace();
                if (_running)
                {
                    EditorGUILayout.LabelField($"(running: {_runningLabel})",
                        EditorStyles.miniLabel, GUILayout.Width(220));
                }
                if (GUILayout.Button("Clear", GUILayout.Width(60)))
                {
                    _logLines.Clear();
                }
            }

            _logScroll = EditorGUILayout.BeginScrollView(_logScroll,
                GUILayout.MinHeight(180), GUILayout.ExpandHeight(true));
            // Show the last few hundred lines only — avoids IMGUI melting on huge logs.
            int start = Mathf.Max(0, _logLines.Count - 400);
            for (int i = start; i < _logLines.Count; i++)
            {
                EditorGUILayout.SelectableLabel(_logLines[i],
                    EditorStyles.label,
                    GUILayout.Height(EditorGUIUtility.singleLineHeight));
            }
            EditorGUILayout.EndScrollView();
        }

        // ---------------------------------------------------------------
        // CLI dispatch
        // ---------------------------------------------------------------

        private bool ValidateReady()
        {
            return !string.IsNullOrEmpty(NpcForgePreferences.DemoDir)
                && Directory.Exists(NpcForgePreferences.DemoDir);
        }

        private void RunCli(params string[] args)
        {
            _running = true;
            _runningLabel = string.Join(" ", args);
            LogLine($"$ npcforge {_runningLabel}");

            var env = new Dictionary<string, string>
            {
                ["GEMINI_API_KEY"] = NpcForgePreferences.GeminiApiKey,
            };

            NpcForgeCliRunner.RunAsync(args, env,
                onComplete: (code, stdout, stderr) =>
                {
                    _running = false;
                    _runningLabel = string.Empty;
                    LogLine(code == 0
                        ? $"[ok] exit={code}"
                        : $"[fail] exit={code}");
                    // Trigger a reimport so Unity sees new .yarn files.
                    if (code == 0) AssetDatabase.Refresh();
                    Repaint();
                },
                onOutputLine: line =>
                {
                    LogLine(line);
                    Repaint();
                });
            Repaint();
        }

        private void LogLine(string line)
        {
            _logLines.Add(line ?? string.Empty);
            _logScroll.y = float.MaxValue;
        }
    }
}
