// NpcForgeUnseenRegistry.cs
//
// Runtime mirror of npcforge's Python unseen module (v0.15.0). Tracks
// mentions the gameplay layer records against slots for characters
// who haven't been authored yet — Gereth's "the foreman who took the
// last drink" becomes one slot accumulating canon until the player
// finally meets that character. At which point the offline Python
// CLI (`npcforge unseen materialize`) produces a full NpcSheet from
// the accumulated canon.
//
// Unity's role: accumulate mentions, persist them, export to the
// Python side. Materialisation happens OFFLINE because it's an LLM
// call against a full character-sheet schema — not a runtime hot path.
//
// JSON layout is byte-compatible with Python's UnseenRegistry so one
// file feeds both runtimes. Python uses a dict of canonical_id →
// UnseenCharacter; JsonUtility can't deserialise dicts, so we emit
// the dict shape manually and parse it with a small regex-based
// reader (same pattern NpcForgePlayerProfile uses).

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    [Serializable]
    public class NpcForgeMentionRecord
    {
        public string source_npc_id;
        public string context;
        public int turn;
        public string scene_context = "";
    }

    [Serializable]
    public class NpcForgeUnseenCharacter
    {
        public string canonical_id;
        public string display_name_hint = "";
        public string role_hint = "";
        public List<NpcForgeMentionRecord> mention_records
            = new List<NpcForgeMentionRecord>();
        public string materialized_as = "";
    }

    public class NpcForgeUnseenRegistry : MonoBehaviour
    {
        [Tooltip("Filename under Application.persistentDataPath. Matches "
                 + "the <demo-dir>/unseen.json name the Python CLI reads.")]
        [SerializeField] private string fileName = "npcforge_unseen.json";

        [Tooltip("Auto-save after declare/record. Turn off for batch "
                 + "inserts and call Save() once at the end.")]
        [SerializeField] private bool autoSave = true;

        [Tooltip("Load from the configured path on Start().")]
        [SerializeField] private bool autoLoadOnStart = true;

        [SerializeField]
        private List<NpcForgeUnseenCharacter> characters
            = new List<NpcForgeUnseenCharacter>();

        [Header("Events")]
        public UnityEvent<string> onSlotDeclared = new UnityEvent<string>();
        public UnityEvent<string, NpcForgeMentionRecord> onMentionRecorded
            = new UnityEvent<string, NpcForgeMentionRecord>();

        public string FullPath =>
            Path.Combine(Application.persistentDataPath, fileName);

        public IReadOnlyList<NpcForgeUnseenCharacter> Characters => characters;

        private void Start()
        {
            if (autoLoadOnStart) Load();
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public NpcForgeUnseenCharacter Get(string canonicalId)
        {
            for (int i = 0; i < characters.Count; i++)
                if (characters[i].canonical_id == canonicalId)
                    return characters[i];
            return null;
        }

        /// <summary>Create a slot if missing; return the existing one
        /// otherwise. Safe to call every session — mentions are
        /// preserved.</summary>
        public NpcForgeUnseenCharacter Declare(
            string canonicalId,
            string displayNameHint = "",
            string roleHint = "")
        {
            if (string.IsNullOrEmpty(canonicalId))
                throw new ArgumentException("canonicalId required", nameof(canonicalId));
            var existing = Get(canonicalId);
            if (existing != null) return existing;

            var fresh = new NpcForgeUnseenCharacter
            {
                canonical_id = canonicalId,
                display_name_hint = displayNameHint ?? "",
                role_hint = roleHint ?? "",
            };
            characters.Add(fresh);
            onSlotDeclared?.Invoke(canonicalId);
            if (autoSave) Save();
            return fresh;
        }

        /// <summary>Append a mention. Throws if the slot hasn't been
        /// declared — typos are usually the cause and should fail loud.</summary>
        public NpcForgeMentionRecord RecordMention(
            string canonicalId,
            string sourceNpcId,
            string context,
            int turn = 0,
            string sceneContext = "")
        {
            var slot = Get(canonicalId);
            if (slot == null)
                throw new InvalidOperationException(
                    $"UnseenRegistry has no slot '{canonicalId}'. "
                    + "Call Declare first.");
            if (string.IsNullOrEmpty(sourceNpcId))
                throw new ArgumentException("sourceNpcId required",
                    nameof(sourceNpcId));

            var record = new NpcForgeMentionRecord
            {
                source_npc_id = sourceNpcId,
                context = context ?? "",
                turn = turn,
                scene_context = sceneContext ?? "",
            };
            slot.mention_records.Add(record);
            onMentionRecorded?.Invoke(canonicalId, record);
            if (autoSave) Save();
            return record;
        }

        /// <summary>True if the slot exists and has not yet been
        /// materialised (materialized_as still empty).</summary>
        public bool StillUnseen(string canonicalId)
        {
            var slot = Get(canonicalId);
            return slot != null && string.IsNullOrEmpty(slot.materialized_as);
        }

        /// <summary>Set by gameplay after the offline materialise step
        /// produces a sheet and the game starts using the new NPC.</summary>
        public void MarkMaterialised(string canonicalId, string newNpcId)
        {
            var slot = Get(canonicalId);
            if (slot == null) return;
            slot.materialized_as = newNpcId ?? "";
            if (autoSave) Save();
        }

        /// <summary>Drop everything. Useful for new-game flows or tests.</summary>
        public void Clear()
        {
            characters.Clear();
            if (autoSave) Save();
        }

        // ---------------------------------------------------------------
        // Persistence — writes + reads Python's dict-keyed shape
        // ---------------------------------------------------------------

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Application.persistentDataPath);
                File.WriteAllText(FullPath, BuildJson());
            }
            catch (Exception ex)
            {
                Debug.LogWarning(
                    $"[NpcForgeUnseenRegistry] save failed: {ex.Message}");
            }
        }

        public void Load()
        {
            if (!File.Exists(FullPath)) return;
            try
            {
                characters = ParseJson(File.ReadAllText(FullPath));
            }
            catch (Exception ex)
            {
                Debug.LogWarning(
                    $"[NpcForgeUnseenRegistry] load failed: {ex.Message}");
            }
        }

        // ---------------------------------------------------------------
        // JSON — dict-keyed shape matching Python
        // ---------------------------------------------------------------
        //
        // Python emits:
        //   {
        //     "schema_version": "1",
        //     "characters": {
        //       "borin_of_grindholt": {
        //         "canonical_id": "borin_of_grindholt",
        //         "display_name_hint": "Borin",
        //         "role_hint": "dwarven foreman of the seam",
        //         "mention_records": [
        //           { "source_npc_id": "...", "context": "...", ... }
        //         ],
        //         "materialized_as": ""
        //       }
        //     }
        //   }
        //
        // We write that shape by hand and read it back with a small
        // regex-based parser so JsonUtility's dict gap doesn't block us.

        public string BuildJson()
        {
            var sb = new StringBuilder();
            sb.AppendLine("{");
            sb.AppendLine("  \"schema_version\": \"1\",");
            sb.Append("  \"characters\": {");
            for (int i = 0; i < characters.Count; i++)
            {
                var c = characters[i];
                if (i > 0) sb.Append(",");
                sb.AppendLine();
                sb.AppendLine($"    \"{Escape(c.canonical_id)}\": {{");
                sb.AppendLine($"      \"canonical_id\": \"{Escape(c.canonical_id)}\",");
                sb.AppendLine($"      \"display_name_hint\": \"{Escape(c.display_name_hint)}\",");
                sb.AppendLine($"      \"role_hint\": \"{Escape(c.role_hint)}\",");
                sb.Append("      \"mention_records\": [");
                for (int j = 0; j < c.mention_records.Count; j++)
                {
                    var m = c.mention_records[j];
                    if (j > 0) sb.Append(",");
                    sb.AppendLine();
                    sb.AppendLine("        {");
                    sb.AppendLine($"          \"source_npc_id\": \"{Escape(m.source_npc_id)}\",");
                    sb.AppendLine($"          \"context\": \"{Escape(m.context)}\",");
                    sb.AppendLine($"          \"turn\": {m.turn},");
                    sb.AppendLine($"          \"scene_context\": \"{Escape(m.scene_context)}\"");
                    sb.Append("        }");
                }
                if (c.mention_records.Count > 0) sb.AppendLine();
                sb.AppendLine((c.mention_records.Count > 0 ? "      " : "") + "],");
                sb.AppendLine($"      \"materialized_as\": \"{Escape(c.materialized_as)}\"");
                sb.Append("    }");
            }
            if (characters.Count > 0) sb.AppendLine();
            sb.Append("  }");
            sb.AppendLine();
            sb.Append("}");
            return sb.ToString();
        }

        public static List<NpcForgeUnseenCharacter> ParseJson(string json)
        {
            var result = new List<NpcForgeUnseenCharacter>();
            if (string.IsNullOrWhiteSpace(json)) return result;

            // Carve out the "characters" object body and iterate its
            // keyed entries. We do a shallow scan that relies on npcforge's
            // own well-formed output; hand-edited JSON with unusual
            // whitespace still parses because the regexes tolerate it.
            var charsMatch = Regex.Match(json,
                "\"characters\"\\s*:\\s*\\{([\\s\\S]*)\\}\\s*\\}\\s*$",
                RegexOptions.Singleline);
            if (!charsMatch.Success) return result;

            string body = charsMatch.Groups[1].Value;
            // Each entry looks like:  "key": { ... }
            // Walk the string tracking brace depth to split entries.
            int i = 0;
            while (i < body.Length)
            {
                // Skip whitespace + commas.
                while (i < body.Length && (char.IsWhiteSpace(body[i]) || body[i] == ','))
                    i++;
                if (i >= body.Length || body[i] != '"') break;

                // Read key.
                int keyStart = ++i;
                while (i < body.Length && body[i] != '"') i++;
                string key = body.Substring(keyStart, i - keyStart);
                i++; // closing quote

                // Skip ":" + whitespace, find opening "{".
                while (i < body.Length && body[i] != '{') i++;
                if (i >= body.Length) break;
                int objStart = i;
                int depth = 0;
                do
                {
                    if (body[i] == '{') depth++;
                    else if (body[i] == '}') depth--;
                    i++;
                } while (i < body.Length && depth > 0);
                string objText = body.Substring(objStart, i - objStart);

                var c = ParseCharacterObject(key, objText);
                if (c != null) result.Add(c);
            }
            return result;
        }

        private static NpcForgeUnseenCharacter ParseCharacterObject(
            string fallbackId, string objText)
        {
            var c = new NpcForgeUnseenCharacter
            {
                canonical_id = ExtractString(objText, "canonical_id") ?? fallbackId,
                display_name_hint = ExtractString(objText, "display_name_hint") ?? "",
                role_hint = ExtractString(objText, "role_hint") ?? "",
                materialized_as = ExtractString(objText, "materialized_as") ?? "",
            };

            // Pull the mention_records array (may be empty).
            var arrMatch = Regex.Match(
                objText, "\"mention_records\"\\s*:\\s*\\[([\\s\\S]*?)\\]");
            if (arrMatch.Success)
            {
                string arr = arrMatch.Groups[1].Value;
                // Each record is a balanced {...} block.
                int i = 0;
                while (i < arr.Length)
                {
                    while (i < arr.Length && arr[i] != '{') i++;
                    if (i >= arr.Length) break;
                    int start = i;
                    int depth = 0;
                    do
                    {
                        if (arr[i] == '{') depth++;
                        else if (arr[i] == '}') depth--;
                        i++;
                    } while (i < arr.Length && depth > 0);
                    string recText = arr.Substring(start, i - start);
                    var rec = new NpcForgeMentionRecord
                    {
                        source_npc_id = ExtractString(recText, "source_npc_id") ?? "",
                        context = ExtractString(recText, "context") ?? "",
                        scene_context = ExtractString(recText, "scene_context") ?? "",
                        turn = ExtractInt(recText, "turn") ?? 0,
                    };
                    c.mention_records.Add(rec);
                }
            }
            return c;
        }

        private static string ExtractString(string body, string field)
        {
            var m = Regex.Match(
                body,
                $"\"{Regex.Escape(field)}\"\\s*:\\s*\"((?:\\\\\"|[^\"])*)\"",
                RegexOptions.Singleline);
            if (!m.Success) return null;
            return Unescape(m.Groups[1].Value);
        }

        private static int? ExtractInt(string body, string field)
        {
            var m = Regex.Match(
                body,
                $"\"{Regex.Escape(field)}\"\\s*:\\s*(-?\\d+)");
            if (!m.Success) return null;
            return int.Parse(m.Groups[1].Value);
        }

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                    .Replace("\n", "\\n").Replace("\r", "\\r")
                    .Replace("\t", "\\t");
        }

        private static string Unescape(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            return s.Replace("\\\"", "\"").Replace("\\\\", "\\")
                    .Replace("\\n", "\n").Replace("\\r", "\r")
                    .Replace("\\t", "\t");
        }
    }
}
