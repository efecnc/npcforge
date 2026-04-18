// NpcForgeMenu.cs
//
// Top-level menu items that drop users into the right flow without
// opening the full EditorWindow. Each item routes to the CLI runner or
// the window, depending on whether there's UI state worth showing.

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public static class NpcForgeMenu
    {
        [MenuItem("Tools/npcforge/Open Panel... %#&n", priority = 10)]
        public static void OpenPanel()
        {
            NpcForgeWindow.Open();
        }

        [MenuItem("Tools/npcforge/Quick Sync to This Project", priority = 11)]
        public static void QuickSync()
        {
            if (!ValidateDemoDir(out string err))
            {
                EditorUtility.DisplayDialog("npcforge", err, "OK");
                return;
            }

            string projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
            if (string.IsNullOrEmpty(projectRoot))
            {
                Debug.LogError("[NpcForge] Could not resolve Unity project root.");
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

            var env = new Dictionary<string, string>
            {
                ["GEMINI_API_KEY"] = NpcForgePreferences.GeminiApiKey,
            };

            Debug.Log($"[NpcForge] running: npcforge {string.Join(" ", args)}");
            NpcForgeCliRunner.RunAsync(args.ToArray(), env,
                onComplete: (code, stdout, stderr) =>
                {
                    if (code == 0)
                    {
                        Debug.Log($"[NpcForge] sync OK\n{stdout}");
                        AssetDatabase.Refresh();
                    }
                    else
                    {
                        Debug.LogError($"[NpcForge] sync failed (exit {code})\n{stderr}\n{stdout}");
                    }
                });
        }

        [MenuItem("Tools/npcforge/Build All (walk-up + barks + lines.csv)", priority = 12)]
        public static void BuildAll()
        {
            if (!ValidateDemoDir(out string err))
            {
                EditorUtility.DisplayDialog("npcforge", err, "OK");
                return;
            }

            var env = new Dictionary<string, string>
            {
                ["GEMINI_API_KEY"] = NpcForgePreferences.GeminiApiKey,
            };
            Debug.Log("[NpcForge] running: npcforge build --mode all");
            NpcForgeCliRunner.RunAsync(
                new[] { "build", "--demo-dir", NpcForgePreferences.DemoDir, "--mode", "all" },
                env,
                onComplete: (code, stdout, stderr) =>
                {
                    if (code == 0)
                        Debug.Log($"[NpcForge] build OK\n{stdout}");
                    else
                        Debug.LogError($"[NpcForge] build failed (exit {code})\n{stderr}\n{stdout}");
                });
        }

        [MenuItem("Tools/npcforge/Documentation", priority = 1000)]
        public static void OpenDocs()
        {
            Application.OpenURL("https://github.com/efecnc/npcforge");
        }

        [MenuItem("Tools/npcforge/Separator_1", true, priority = 19)]
        private static bool Sep1() { return false; } // noop — makes the menu separator land between sections

        private static bool ValidateDemoDir(out string error)
        {
            if (string.IsNullOrEmpty(NpcForgePreferences.DemoDir))
            {
                error = "Set the npcforge project directory in Tools → npcforge → Open Panel first.";
                return false;
            }
            if (!Directory.Exists(NpcForgePreferences.DemoDir))
            {
                error = $"npcforge project directory does not exist:\n{NpcForgePreferences.DemoDir}";
                return false;
            }
            error = null;
            return true;
        }
    }
}
