// NpcForgeYamlReader.cs
//
// Minimal YAML reader tailored to npcforge's characters.yaml schema.
// Extracts just enough per-NPC info for the Browser window to display:
// voice, role, motivations, relationships, knowledge, state evolution,
// and the various list-of-strings fields.
//
// We deliberately don't pull in YamlDotNet or SharpYaml — both are
// heavy dependencies that clash with Unity's packaging rules. The
// schema is simple enough to parse with a small indent-aware state
// machine; when a user's yaml trips this parser up we log and skip
// that NPC rather than crash.
//
// If the package ever grows to need arbitrary YAML parsing we should
// revisit this and depend on YamlDotNet via a Package Manager entry.

using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public class NpcSummary
    {
        public string Id = "";
        public string Name = "";
        public string Role = "";
        public string Voice = "";
        public string Background = "";
        public string Secret = "";
        public string VocabularyCeiling = "";
        public List<string> Motivations = new List<string>();
        public List<string> SpeechQuirks = new List<string>();
        public List<string> SampleLines = new List<string>();
        public List<string> ForbiddenWords = new List<string>();
        public List<string> AccentMarkers = new List<string>();
        public List<string> AllowedIntents = new List<string>();
        public List<string> ReactsTo = new List<string>();
        // Relationship rendered as { "target_id": "opinion — reason" }
        public List<KeyValuePair<string, string>> Relationships = new List<KeyValuePair<string, string>>();
        // Knowledge rendered as { "id": "fact / gate / sample notes" }
        public List<KeyValuePair<string, string>> Knowledge = new List<KeyValuePair<string, string>>();
        // State evolution rendered as { "trigger": "voice_shift" }
        public List<KeyValuePair<string, string>> StateEvolution = new List<KeyValuePair<string, string>>();

        public bool Matches(string lowercaseFilter)
        {
            if (string.IsNullOrEmpty(lowercaseFilter)) return true;
            if (Id.ToLowerInvariant().Contains(lowercaseFilter)) return true;
            if (Name.ToLowerInvariant().Contains(lowercaseFilter)) return true;
            if (Role.ToLowerInvariant().Contains(lowercaseFilter)) return true;
            return false;
        }
    }

    public static class NpcForgeYamlReader
    {
        /// <summary>Parse ``<demoDir>/characters.yaml`` into an ordered list of
        /// :class:`NpcSummary`. Returns an empty list when the file is
        /// missing, malformed, or the demo dir is not configured.</summary>
        public static List<NpcSummary> LoadSummaries(string demoDir)
        {
            var result = new List<NpcSummary>();
            if (string.IsNullOrEmpty(demoDir)) return result;
            string path = Path.Combine(demoDir, "characters.yaml");
            if (!File.Exists(path)) return result;

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[NpcForge] Could not read {path}: {ex.Message}");
                return result;
            }

            bool inNpcs = false;
            NpcSummary current = null;
            // Track nested "sections" so we know what a list of bullets belongs to.
            string section = null;
            string nestedHeader = null;    // "relationships" | "knowledge" | "state_evolution"
            Dictionary<string, string> pendingNested = null;

            void FlushNested()
            {
                if (pendingNested == null || current == null) return;
                if (nestedHeader == "relationships")
                {
                    string id = pendingNested.TryGetValue("npc_id", out var nid) ? nid : "(?)";
                    string op = pendingNested.TryGetValue("opinion", out var opt) ? opt : "";
                    string reason = pendingNested.TryGetValue("reason", out var r) ? r : "";
                    string body = op;
                    if (!string.IsNullOrEmpty(reason)) body += " — " + reason;
                    current.Relationships.Add(new KeyValuePair<string, string>(id, body));
                }
                else if (nestedHeader == "knowledge")
                {
                    string id = pendingNested.TryGetValue("id", out var kid) ? kid : "(?)";
                    string fact = pendingNested.TryGetValue("fact", out var f) ? f : "";
                    string gate = pendingNested.TryGetValue("gate", out var g) ? g : "";
                    string body = fact;
                    if (!string.IsNullOrEmpty(gate)) body += "\nGate: " + gate;
                    current.Knowledge.Add(new KeyValuePair<string, string>(id, body));
                }
                else if (nestedHeader == "state_evolution")
                {
                    string trig = pendingNested.TryGetValue("trigger", out var t) ? t : "(?)";
                    string shift = pendingNested.TryGetValue("voice_shift", out var sh) ? sh : "";
                    current.StateEvolution.Add(new KeyValuePair<string, string>(trig, shift));
                }
                pendingNested = null;
            }

            void FlushNpc()
            {
                FlushNested();
                if (current != null && !string.IsNullOrEmpty(current.Id))
                {
                    result.Add(current);
                }
                current = null;
                section = null;
                nestedHeader = null;
            }

            for (int i = 0; i < lines.Length; i++)
            {
                string raw = lines[i];
                string trimmed = raw.TrimEnd();
                if (trimmed.Length == 0) continue;
                if (trimmed.TrimStart().StartsWith("#")) continue;

                int indent = 0;
                while (indent < raw.Length && raw[indent] == ' ') indent++;

                if (!inNpcs)
                {
                    if (trimmed.StartsWith("npcs:")) inNpcs = true;
                    continue;
                }

                string body = trimmed.TrimStart();

                // A new NPC entry starts with "  - id: <slug>"
                if (indent == 2 && body.StartsWith("- id:"))
                {
                    FlushNpc();
                    current = new NpcSummary { Id = ValueAfterKey(body, "- id:") };
                    continue;
                }

                if (current == null) continue;

                // Nested blocks at indent >= 6 belong to relationships/knowledge/evolution.
                if (indent >= 6 && nestedHeader != null)
                {
                    if (body.StartsWith("- ") && !body.Contains(":"))
                    {
                        // Bullet line without a key — irrelevant for our nested blocks.
                        continue;
                    }
                    if (body.StartsWith("- "))
                    {
                        FlushNested();
                        pendingNested = new Dictionary<string, string>();
                        body = body.Substring(2);
                    }
                    if (body.Contains(":"))
                    {
                        int colon = body.IndexOf(':');
                        string k = body.Substring(0, colon).Trim();
                        string v = body.Substring(colon + 1).Trim();
                        if (v == ">" || v == "|")
                        {
                            // Folded / literal scalar — collect following deeper-indented lines.
                            v = CollectFolded(lines, ref i, indent);
                        }
                        if (pendingNested != null)
                        {
                            pendingNested[k] = StripQuotes(v);
                        }
                    }
                    continue;
                }

                if (indent == 4)
                {
                    // Top-level NPC field.
                    FlushNested();
                    nestedHeader = null;
                    section = null;

                    if (body.Contains(":"))
                    {
                        int colon = body.IndexOf(':');
                        string key = body.Substring(0, colon).Trim();
                        string value = body.Substring(colon + 1).Trim();

                        if (value == ">" || value == "|")
                        {
                            value = CollectFolded(lines, ref i, indent);
                        }

                        switch (key)
                        {
                            case "name": current.Name = StripQuotes(value); break;
                            case "role": current.Role = StripQuotes(value); break;
                            case "voice": current.Voice = StripQuotes(value); break;
                            case "background": current.Background = StripQuotes(value); break;
                            case "secret": current.Secret = StripQuotes(value); break;
                            case "vocabulary_ceiling": current.VocabularyCeiling = StripQuotes(value); break;
                            case "motivations": section = "motivations"; break;
                            case "speech_quirks": section = "speech_quirks"; break;
                            case "sample_lines": section = "sample_lines"; break;
                            case "forbidden_words": section = "forbidden_words"; break;
                            case "accent_markers": section = "accent_markers"; break;
                            case "allowed_intents": section = "allowed_intents"; break;
                            case "reacts_to": section = "reacts_to"; break;
                            case "relationships": nestedHeader = "relationships"; break;
                            case "knowledge": nestedHeader = "knowledge"; break;
                            case "state_evolution": nestedHeader = "state_evolution"; break;
                        }
                    }
                    continue;
                }

                if (indent >= 6 && body.StartsWith("- ") && section != null)
                {
                    string item = body.Substring(2).Trim();
                    item = StripQuotes(item);
                    switch (section)
                    {
                        case "motivations": current.Motivations.Add(item); break;
                        case "speech_quirks": current.SpeechQuirks.Add(item); break;
                        case "sample_lines": current.SampleLines.Add(item); break;
                        case "forbidden_words": current.ForbiddenWords.Add(item); break;
                        case "accent_markers": current.AccentMarkers.Add(item); break;
                        case "allowed_intents": current.AllowedIntents.Add(item); break;
                        case "reacts_to": current.ReactsTo.Add(item); break;
                    }
                }
            }

            FlushNpc();
            return result;
        }

        private static string ValueAfterKey(string line, string key)
        {
            int idx = line.IndexOf(key);
            if (idx < 0) return "";
            return line.Substring(idx + key.Length).Trim();
        }

        private static string StripQuotes(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            if ((s.StartsWith("\"") && s.EndsWith("\"")) ||
                (s.StartsWith("'") && s.EndsWith("'")))
            {
                return s.Substring(1, s.Length - 2);
            }
            return s;
        }

        /// <summary>Consume a YAML folded (``>``) or literal (``|``) block
        /// scalar starting after ``i``; return the joined text and advance
        /// ``i`` past it.</summary>
        private static string CollectFolded(string[] lines, ref int i, int ownerIndent)
        {
            var sb = new System.Text.StringBuilder();
            int j = i + 1;
            while (j < lines.Length)
            {
                string nxt = lines[j];
                int ind = 0;
                while (ind < nxt.Length && nxt[ind] == ' ') ind++;
                if (nxt.TrimEnd().Length == 0) { j++; continue; }
                if (ind <= ownerIndent) break;
                if (sb.Length > 0) sb.Append(' ');
                sb.Append(nxt.Trim());
                j++;
            }
            i = j - 1;
            return sb.ToString();
        }
    }
}
