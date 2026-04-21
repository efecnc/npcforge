// NpcForgeLinesCsvImporter.cs
//
// Watches Assets/NpcForge/Dialogue/lines.csv and regenerates a sibling
// NpcForgeLineMetadata.asset whenever the CSV changes. Designers get an
// up-to-date runtime-queryable database without running any commands
// themselves; engine-sync → lines.csv → metadata asset, automatically.
//
// Why AssetPostprocessor instead of ScriptedImporter? ScriptedImporter
// registers against a file *extension*, which would grab every .csv in
// the project. There's no way to scope it to just Dialogue/lines.csv.
// The postprocessor lets us filter by path exactly.
//
// A menu item also lets users force-regenerate on demand, in case the
// auto-trigger misses (rare, but e.g. if lines.csv was committed before
// the package was installed).

using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using Altai.NpcForge;

namespace Altai.NpcForge.Editor
{
    public class NpcForgeLinesCsvImporter : AssetPostprocessor
    {
        public const string LinesCsvPath = "Assets/NpcForge/Dialogue/lines.csv";
        public const string MetadataPath = "Assets/NpcForge/Dialogue/NpcForgeLineMetadata.asset";

        private static void OnPostprocessAllAssets(
            string[] imported, string[] deleted, string[] moved, string[] movedFrom)
        {
            foreach (string p in imported)
            {
                if (string.Equals(p, LinesCsvPath, StringComparison.OrdinalIgnoreCase))
                {
                    // Defer the regeneration to after Unity's current
                    // import pass so we don't re-trigger ourselves.
                    EditorApplication.delayCall += RegenerateFromDisk;
                    break;
                }
            }
        }

        [MenuItem("Tools/npcforge/Rebuild Line Metadata from lines.csv", priority = 24)]
        public static void RebuildMenu()
        {
            RegenerateFromDisk();
        }

        /// <summary>Read lines.csv from disk and (re)write the
        /// NpcForgeLineMetadata asset. No-op when the CSV is missing.</summary>
        public static void RegenerateFromDisk()
        {
            if (!File.Exists(LinesCsvPath))
            {
                Debug.LogWarning($"[NpcForge] No lines.csv at {LinesCsvPath}. " +
                                 "Run `npcforge build` + `engine-sync` first.");
                return;
            }
            string text;
            try
            {
                text = File.ReadAllText(LinesCsvPath);
            }
            catch (IOException ex)
            {
                Debug.LogError($"[NpcForge] Could not read lines.csv: {ex.Message}");
                return;
            }

            List<NpcForgeLineRecord> records = Parse(text);

            var asset = AssetDatabase.LoadAssetAtPath<NpcForgeLineMetadata>(MetadataPath);
            bool created = false;
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<NpcForgeLineMetadata>();
                // Make sure the folder exists before writing.
                EnsureFolder(Path.GetDirectoryName(MetadataPath));
                AssetDatabase.CreateAsset(asset, MetadataPath);
                created = true;
            }

            asset.SetRecords(records);
            EditorUtility.SetDirty(asset);
            AssetDatabase.SaveAssets();
            Debug.Log($"[NpcForge] {(created ? "Created" : "Updated")} line metadata " +
                      $"with {records.Count} record(s) at {MetadataPath}.");
        }

        // -----------------------------------------------------------------
        // CSV parsing — lightweight, matches npcforge's audio.py output.
        // Handles quoted fields with embedded commas + escaped quotes
        // ("" inside "..."). Doesn't handle newlines-within-fields
        // because lines.csv never emits those.
        // -----------------------------------------------------------------

        private static readonly string[] _expectedHeader =
        {
            "line_id", "npc_id", "speaker", "context",
            "source_file", "emotion", "intensity", "duration_sec", "text",
        };

        public static List<NpcForgeLineRecord> Parse(string csv)
        {
            var list = new List<NpcForgeLineRecord>();
            if (string.IsNullOrEmpty(csv)) return list;

            // Split by line — lines.csv never emits embedded newlines in fields.
            string[] lines = csv.Replace("\r\n", "\n").Split('\n');
            if (lines.Length == 0) return list;

            // Header sanity — accept any column order by mapping names to indices.
            var header = ParseRow(lines[0]);
            var colIdx = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < header.Count; i++) colIdx[header[i]] = i;

            foreach (var expected in _expectedHeader)
            {
                if (!colIdx.ContainsKey(expected))
                {
                    Debug.LogWarning($"[NpcForge] lines.csv missing expected column '{expected}' — " +
                                     "records from that column will be empty.");
                }
            }

            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                var row = ParseRow(lines[i]);
                if (row.Count == 0) continue;

                var r = new NpcForgeLineRecord
                {
                    lineId     = Get(row, colIdx, "line_id"),
                    npcId      = Get(row, colIdx, "npc_id"),
                    speaker    = Get(row, colIdx, "speaker"),
                    context    = Get(row, colIdx, "context"),
                    sourceFile = Get(row, colIdx, "source_file"),
                    emotion    = Get(row, colIdx, "emotion", fallback: "neutral"),
                    intensity  = Get(row, colIdx, "intensity", fallback: "medium"),
                    text       = Get(row, colIdx, "text"),
                };
                float.TryParse(Get(row, colIdx, "duration_sec"),
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture,
                    out r.durationSec);
                list.Add(r);
            }
            return list;
        }

        private static string Get(IList<string> row, Dictionary<string, int> idx, string col, string fallback = "")
        {
            if (!idx.TryGetValue(col, out int i)) return fallback;
            if (i < 0 || i >= row.Count) return fallback;
            return row[i] ?? fallback;
        }

        /// <summary>Parse one CSV row into fields. Handles "quoted" fields
        /// with embedded commas and "" escaped quotes.</summary>
        public static List<string> ParseRow(string row)
        {
            var cells = new List<string>();
            if (row == null) return cells;

            var sb = new System.Text.StringBuilder();
            bool inQuote = false;
            for (int i = 0; i < row.Length; i++)
            {
                char c = row[i];
                if (inQuote)
                {
                    if (c == '"' && i + 1 < row.Length && row[i + 1] == '"')
                    {
                        sb.Append('"');
                        i++; // swallow the escaped second quote
                    }
                    else if (c == '"')
                    {
                        inQuote = false;
                    }
                    else
                    {
                        sb.Append(c);
                    }
                }
                else
                {
                    if (c == ',')
                    {
                        cells.Add(sb.ToString());
                        sb.Length = 0;
                    }
                    else if (c == '"' && sb.Length == 0)
                    {
                        inQuote = true;
                    }
                    else
                    {
                        sb.Append(c);
                    }
                }
            }
            cells.Add(sb.ToString());
            return cells;
        }

        private static void EnsureFolder(string folder)
        {
            if (string.IsNullOrEmpty(folder) || AssetDatabase.IsValidFolder(folder)) return;
            string parent = Path.GetDirectoryName(folder);
            if (!string.IsNullOrEmpty(parent)) EnsureFolder(parent);
            string name = Path.GetFileName(folder);
            AssetDatabase.CreateFolder(parent, name);
        }
    }
}
