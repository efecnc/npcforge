// NpcForgePanelUIT.cs
//
// Modern UI Toolkit (UIElements) counterpart to NpcForgeWindow. Same
// functionality — settings, generation buttons, sync, live log — but
// built from VisualElements with CSS-style inline stylesheets so it
// matches Unity 2022+'s native panel aesthetic.
//
// Lives alongside the IMGUI panel rather than replacing it so users on
// older workflows can keep what they know while new installs get the
// modern look by default. Pick either from Tools → npcforge.
//
// No UXML / USS files on disk — the whole panel is assembled in code.
// Keeps the package a single folder of .cs files and avoids resource-
// loading ceremony.

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.UIElements;
using UnityEngine;
using UnityEngine.UIElements;

namespace Altai.NpcForge.Editor
{
    public class NpcForgePanelUIT : EditorWindow
    {
        private TextField _binaryField;
        private TextField _demoDirField;
        private TextField _apiKeyField;
        private Toggle _installScriptsToggle;
        private ObjectField _yarnProjectField;
        private ScrollView _logScroll;
        private Label _statusLabel;
        private Button _cancelBusy;
        private bool _running;

        [MenuItem("Tools/npcforge/Open Panel (UI Toolkit)...", priority = 15)]
        public static void Open()
        {
            var wnd = GetWindow<NpcForgePanelUIT>();
            wnd.titleContent = new GUIContent("npcforge (UIT)");
            wnd.minSize = new Vector2(520, 620);
            wnd.Show();
        }

        public void CreateGUI()
        {
            var root = rootVisualElement;
            root.style.paddingLeft = 12;
            root.style.paddingRight = 12;
            root.style.paddingTop = 12;
            root.style.paddingBottom = 12;

            root.Add(BuildHeader());
            root.Add(BuildSettings());
            root.Add(BuildGeneration());
            root.Add(BuildSync());
            root.Add(BuildLog());
        }

        // ---------------------------------------------------------------
        // Sections
        // ---------------------------------------------------------------

        private static VisualElement BuildHeader()
        {
            var v = new VisualElement();
            var title = new Label("npcforge")
            {
                style =
                {
                    fontSize = 18,
                    unityFontStyleAndWeight = FontStyle.Bold,
                    marginBottom = 2,
                },
            };
            var sub = new Label("Character + dialogue generator for Yarn Spinner / Unity.")
            {
                style =
                {
                    color = new StyleColor(new Color(0.7f, 0.7f, 0.7f)),
                    fontSize = 11,
                    marginBottom = 10,
                },
            };
            v.Add(title);
            v.Add(sub);
            return v;
        }

        private VisualElement BuildSettings()
        {
            var box = Panel("Settings");

            _binaryField = new TextField("npcforge binary")
            {
                value = NpcForgePreferences.NpcforgePath,
                tooltip = "Absolute path to the npcforge CLI, or 'npcforge' if on PATH.",
            };
            _binaryField.RegisterValueChangedCallback(e => NpcForgePreferences.NpcforgePath = e.newValue);
            box.Add(_binaryField);

            var dirRow = new VisualElement { style = { flexDirection = FlexDirection.Row } };
            _demoDirField = new TextField("Project directory")
            {
                value = NpcForgePreferences.DemoDir,
                tooltip = "Directory holding characters.yaml, variables.yaml, lore/.",
                style = { flexGrow = 1 },
            };
            _demoDirField.RegisterValueChangedCallback(e => NpcForgePreferences.DemoDir = e.newValue);
            dirRow.Add(_demoDirField);
            var browse = new Button(() =>
            {
                string picked = EditorUtility.OpenFolderPanel(
                    "Select npcforge project directory",
                    NpcForgePreferences.DemoDir, string.Empty);
                if (!string.IsNullOrEmpty(picked))
                {
                    NpcForgePreferences.DemoDir = picked;
                    _demoDirField.SetValueWithoutNotify(picked);
                }
            })
            {
                text = "Browse",
                style = { width = 70 },
            };
            dirRow.Add(browse);
            box.Add(dirRow);

            _apiKeyField = new TextField("GEMINI_API_KEY")
            {
                value = NpcForgePreferences.GeminiApiKey,
                isPasswordField = true,
                tooltip = "Passed as an env var to each CLI call; stored in EditorPrefs only.",
            };
            _apiKeyField.RegisterValueChangedCallback(e => NpcForgePreferences.GeminiApiKey = e.newValue);
            box.Add(_apiKeyField);

            _installScriptsToggle = new Toggle("Install runtime scripts on first sync")
            {
                value = NpcForgePreferences.InstallScriptsOnFirstSync,
                tooltip = "Only copies C# scripts if absent — safe to leave on.",
            };
            _installScriptsToggle.RegisterValueChangedCallback(
                e => NpcForgePreferences.InstallScriptsOnFirstSync = e.newValue);
            box.Add(_installScriptsToggle);

            // Yarn Project picker — see NpcForgeWindow for the reflection trick.
            var yarnType = GetYarnProjectType() ?? typeof(ScriptableObject);
            _yarnProjectField = new ObjectField("Default Yarn Project")
            {
                objectType = yarnType,
                allowSceneObjects = false,
                tooltip = "New .yarn files under Assets/NpcForge/Dialogue/ get " +
                          "wired into this Yarn Project automatically.",
            };
            string guid = NpcForgePreferences.YarnProjectGuid;
            if (!string.IsNullOrEmpty(guid))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (!string.IsNullOrEmpty(path))
                    _yarnProjectField.value = AssetDatabase.LoadAssetAtPath(path, yarnType);
            }
            _yarnProjectField.RegisterValueChangedCallback(e =>
            {
                if (e.newValue == null)
                {
                    NpcForgePreferences.YarnProjectGuid = string.Empty;
                }
                else
                {
                    string p = AssetDatabase.GetAssetPath(e.newValue);
                    NpcForgePreferences.YarnProjectGuid = AssetDatabase.AssetPathToGUID(p);
                }
            });
            box.Add(_yarnProjectField);

            return box;
        }

        private VisualElement BuildGeneration()
        {
            var box = Panel("Generate");
            box.Add(PillButton("World Profile (infer from lore)",
                () => RunCli("world", "infer", "--demo-dir", NpcForgePreferences.DemoDir)));
            box.Add(PillButton("Generate NPCs (5)",
                () => RunCli("gen", "npcs", "--demo-dir", NpcForgePreferences.DemoDir, "--n", "5")));
            box.Add(PillButton("Build All (walk-up + barks + lines.csv)",
                () => RunCli("build", "--demo-dir", NpcForgePreferences.DemoDir, "--mode", "all")));
            box.Add(PillButton("Generate time-of-day greetings",
                () => RunCli("gen", "greetings", "--demo-dir", NpcForgePreferences.DemoDir)));
            box.Add(PillButton("Generate repeat-greetings (n=3)",
                () => RunCli("gen", "repeat-greeting", "--demo-dir", NpcForgePreferences.DemoDir, "--n", "3")));
            return box;
        }

        private VisualElement BuildSync()
        {
            var box = Panel("Sync into this Unity project");
            box.Add(new HelpBox(
                "Copies npcforge's out/ folder into Assets/NpcForge/Dialogue/. " +
                "Yarn Spinner reimports on the next tick.",
                HelpBoxMessageType.Info));
            box.Add(PillButton("Sync now", () =>
            {
                string projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
                var args = new List<string>
                {
                    "engine-sync",
                    "--engine", "unity",
                    "--demo-dir", NpcForgePreferences.DemoDir,
                    "--project-dir", projectRoot,
                };
                if (NpcForgePreferences.InstallScriptsOnFirstSync) args.Add("--install-scripts");
                RunCli(args.ToArray());
            }));
            box.Add(PillButton("Dry-run sync", () =>
            {
                string projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
                RunCli("engine-sync",
                    "--engine", "unity",
                    "--demo-dir", NpcForgePreferences.DemoDir,
                    "--project-dir", projectRoot,
                    "--dry-run", "--verbose");
            }));
            return box;
        }

        private VisualElement BuildLog()
        {
            var box = Panel("Log");

            var toolbar = new VisualElement { style = { flexDirection = FlexDirection.Row, marginBottom = 4 } };
            _statusLabel = new Label("idle") { style = { color = new StyleColor(new Color(0.7f, 0.7f, 0.7f)), flexGrow = 1 } };
            toolbar.Add(_statusLabel);
            toolbar.Add(new Button(() => _logScroll.Clear()) { text = "Clear", style = { width = 60 } });
            box.Add(toolbar);

            _logScroll = new ScrollView(ScrollViewMode.Vertical)
            {
                style = { minHeight = 180, flexGrow = 1 },
            };
            _logScroll.AddToClassList("unity-base-field");
            box.Add(_logScroll);
            return box;
        }

        // ---------------------------------------------------------------
        // Layout helpers
        // ---------------------------------------------------------------

        private static VisualElement Panel(string title)
        {
            var v = new VisualElement
            {
                style =
                {
                    marginBottom = 10,
                    paddingLeft = 10,
                    paddingRight = 10,
                    paddingTop = 8,
                    paddingBottom = 8,
                    backgroundColor = new StyleColor(new Color(0f, 0f, 0f, 0.06f)),
                    borderTopLeftRadius = 6, borderTopRightRadius = 6,
                    borderBottomLeftRadius = 6, borderBottomRightRadius = 6,
                },
            };
            v.Add(new Label(title)
            {
                style =
                {
                    unityFontStyleAndWeight = FontStyle.Bold,
                    fontSize = 12,
                    marginBottom = 6,
                },
            });
            return v;
        }

        private static Button PillButton(string text, System.Action onClick)
        {
            var b = new Button(onClick) { text = text };
            b.style.marginTop = 2;
            b.style.marginBottom = 2;
            b.style.height = 26;
            return b;
        }

        // ---------------------------------------------------------------
        // CLI dispatch (shared with the IMGUI panel)
        // ---------------------------------------------------------------

        private void RunCli(params string[] args)
        {
            if (_running) return;
            _running = true;
            _statusLabel.text = "running: " + string.Join(" ", args);
            AppendLog("$ npcforge " + string.Join(" ", args));

            var env = new Dictionary<string, string>
            {
                ["GEMINI_API_KEY"] = NpcForgePreferences.GeminiApiKey,
            };
            NpcForgeCliRunner.RunAsync(args, env,
                onComplete: (code, stdout, stderr) =>
                {
                    _running = false;
                    _statusLabel.text = code == 0
                        ? "ok (exit 0)"
                        : $"fail (exit {code})";
                    AppendLog(code == 0 ? "[ok]" : $"[fail exit={code}]");
                    if (code == 0) AssetDatabase.Refresh();
                },
                onOutputLine: line => AppendLog(line));
        }

        private void AppendLog(string line)
        {
            if (_logScroll == null) return;
            var l = new Label(line ?? string.Empty);
            l.style.whiteSpace = WhiteSpace.Normal;
            l.style.fontSize = 11;
            _logScroll.Add(l);
            _logScroll.scrollOffset = new Vector2(0f, float.MaxValue);
        }

        // ---------------------------------------------------------------
        // Yarn Spinner type lookup (shared logic with IMGUI panel)
        // ---------------------------------------------------------------

        private static System.Type _cachedYarnProjectType;
        private static System.Type GetYarnProjectType()
        {
            if (_cachedYarnProjectType != null) return _cachedYarnProjectType;
            foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                var t = asm.GetType("Yarn.Unity.YarnProject");
                if (t != null) { _cachedYarnProjectType = t; return t; }
            }
            return null;
        }
    }
}
