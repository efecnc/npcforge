// NpcForgeYarnAssetPostprocessor.cs
//
// Detects new .yarn files landing under Assets/NpcForge/Dialogue/ (the
// engine-sync target) and pokes a configured Yarn Project so it picks
// them up without the user having to drag files into the project's
// source list.
//
// Why reimport the Yarn Project instead of editing it directly? Yarn
// Spinner has switched its Yarn Project format more than once (.asset
// ScriptableObject, then JSON-based .yarnproject). Firing
// AssetDatabase.ImportAsset with ForceUpdate re-runs whichever importer
// Yarn Spinner ships in the user's version, and the glob-based source
// file scanning picks up the new .yarn files automatically.
//
// If no Yarn Project is configured the postprocessor logs the count and
// points the user at the panel's "Default Yarn Project" field. If
// exactly one YarnProject exists in the project we auto-select it and
// persist the choice — covers 95% of small projects out of the box.

using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public class NpcForgeYarnAssetPostprocessor : AssetPostprocessor
    {
        /// <summary>Root path that engine-sync writes into. Kept in sync
        /// with the Python-side engine adapter (<c>engines/unity.py</c>).</summary>
        public const string DialogueRoot = "Assets/NpcForge/Dialogue";

        private static void OnPostprocessAllAssets(
            string[] importedAssets,
            string[] deletedAssets,
            string[] movedAssets,
            string[] movedFromAssetPaths)
        {
            var newYarn = new List<string>();
            foreach (string p in importedAssets)
            {
                if (string.IsNullOrEmpty(p)) continue;
                if (!p.EndsWith(".yarn")) continue;
                // Keep the filter narrow — only files npcforge itself
                // placed into the dialogue tree. Avoids stomping on any
                // other .yarn the user authored outside that folder.
                if (!p.StartsWith(DialogueRoot)) continue;
                newYarn.Add(p);
            }
            if (newYarn.Count == 0) return;

            string projectPath = ResolveYarnProjectPath();
            if (string.IsNullOrEmpty(projectPath))
            {
                Debug.Log($"[NpcForge] Imported {newYarn.Count} .yarn file(s). " +
                          "No default Yarn Project set — assign one in " +
                          "Tools → npcforge → Open Panel… → Settings → Default Yarn Project.");
                return;
            }

            // Force the Yarn Project to re-run its importer so its glob-based
            // source scanning sweeps up the new .yarn files. ForceUpdate is
            // required because the project asset itself didn't change — only
            // its dependencies did.
            AssetDatabase.ImportAsset(projectPath, ImportAssetOptions.ForceUpdate);
            Debug.Log($"[NpcForge] Wired {newYarn.Count} new .yarn file(s) into {projectPath}");
        }

        /// <summary>Resolve the configured Yarn Project's asset path. Falls
        /// back to "exactly one YarnProject in the project" heuristic and
        /// persists that auto-selection so subsequent runs are stable.</summary>
        private static string ResolveYarnProjectPath()
        {
            string guid = NpcForgePreferences.YarnProjectGuid;
            if (!string.IsNullOrEmpty(guid))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (!string.IsNullOrEmpty(path)) return path;

                // Stored GUID no longer resolves — the asset was moved or
                // deleted. Clear it so we fall through to auto-detection
                // and don't keep retrying a dead GUID.
                NpcForgePreferences.YarnProjectGuid = string.Empty;
            }

            // t:YarnProject works when Yarn Spinner is installed (its
            // ScriptableObject type is registered with the asset database);
            // returns nothing otherwise and we log the "no project" message.
            string[] found = AssetDatabase.FindAssets("t:YarnProject");
            if (found == null || found.Length == 0) return null;
            if (found.Length > 1) return null; // ambiguous — require an explicit pick

            string onlyGuid = found[0];
            string onlyPath = AssetDatabase.GUIDToAssetPath(onlyGuid);
            NpcForgePreferences.YarnProjectGuid = onlyGuid;
            Debug.Log($"[NpcForge] Auto-selected Yarn Project: {onlyPath}. " +
                      "Change it via Tools → npcforge → Open Panel…");
            return onlyPath;
        }
    }
}
