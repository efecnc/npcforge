// NpcForgeImprovClient.cs
//
// Runtime client for v0.12.0 lore-consistent improvisation.
//
// npcforge is model-agnostic — we don't ship an HTTP client for
// Gemini / OpenAI / Anthropic / local servers. Games bring their own
// LLM delegate; we provide:
//
//   1. IDF-weighted token-overlap retrieval over a lore bundle, ported
//      from the Python side's retrieve_lore_chunks.
//   2. Prompt composition: concatenates the pre-rendered character
//      sheet block (baked offline via `npcforge export improv-context`),
//      the retrieved lore snippets, and the rules block.
//   3. Structured-response parsing (the ImprovReply schema) so callers
//      get back a typed struct instead of a string.
//
// Wiring:
//   - Drop NpcForgeImprovClient on an NPC GameObject.
//   - Assign the *.json file written by `npcforge export improv-context`
//     as a TextAsset in the Inspector.
//   - From game code, call ``RequestImprov(query, onReply)``. The
//     component builds the prompt and invokes the delegate you
//     registered via SetLlmDelegate. Your delegate makes the HTTP call
//     to the chosen LLM and returns the JSON response; we parse it
//     into ImprovReply and hand it back via the onReply callback.
//
// The delegate shape is explicit (Func<string systemPrompt, string
// userQuery, CancellationToken, Task<string>>) so you can swap in
// OpenAI / Gemini / Anthropic / a local mock without touching the
// component.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    // ---------------------------------------------------------------
    // Context bundle — matches the Python export shape
    // ---------------------------------------------------------------

    [Serializable]
    public class NpcForgeImprovContext
    {
        public string schema_version = "1";
        public string npc_id;
        public string npc_name;
        public string character_sheet_block;
        public string world_bible;
        public string rules_block;
    }

    // ---------------------------------------------------------------
    // Structured-response — matches Python's ImprovReply schema
    // ---------------------------------------------------------------

    [Serializable]
    public class NpcForgeImprovReply
    {
        public string text = "";
        public string used_gate_id = "";
        public string declined_reason = "";
    }

    // ---------------------------------------------------------------
    // Delegate contract
    // ---------------------------------------------------------------

    /// <summary>The caller provides one of these. Receives the composed
    /// system prompt + the raw player query; must return the raw JSON
    /// string of an ImprovReply (text, used_gate_id, declined_reason).
    /// Errors should throw — the client catches and fires the error
    /// callback.</summary>
    public delegate Task<string> NpcForgeImprovLlmDelegate(
        string systemPrompt,
        string userQuery,
        CancellationToken ct);

    // ---------------------------------------------------------------
    // Component
    // ---------------------------------------------------------------

    public class NpcForgeImprovClient : MonoBehaviour
    {
        [Tooltip("The JSON bundle produced by `npcforge export " +
                 "improv-context --npc X`. Baked offline so the runtime " +
                 "doesn't need to parse YAML at load time.")]
        [SerializeField] private TextAsset contextJson;

        [Tooltip("Number of lore chunks to retrieve per query. Lower = " +
                 "cheaper LLM call; higher = more grounding.")]
        [SerializeField, Min(0)] private int topKLore = 3;

        [Header("Events")]
        public UnityEvent<NpcForgeImprovReply> onReplyReceived
            = new UnityEvent<NpcForgeImprovReply>();

        public UnityEvent<string> onError = new UnityEvent<string>();

        private NpcForgeImprovContext _ctx;
        private NpcForgeImprovLlmDelegate _llm;

        public string NpcId => _ctx != null ? _ctx.npc_id : string.Empty;
        public bool IsReady => _ctx != null && _llm != null;

        private void Start()
        {
            if (contextJson != null) LoadContextJson(contextJson.text);
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public void LoadContextJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                _ctx = null;
                return;
            }
            _ctx = JsonUtility.FromJson<NpcForgeImprovContext>(json);
            if (_ctx == null)
                Debug.LogWarning($"[NpcForgeImprovClient] empty/invalid context JSON on '{name}'");
        }

        public void LoadContextFile(string path)
        {
            if (!File.Exists(path))
            {
                Debug.LogWarning($"[NpcForgeImprovClient] context file not found at {path}");
                return;
            }
            LoadContextJson(File.ReadAllText(path));
        }

        /// <summary>Register the LLM delegate. Required before
        /// <see cref="RequestImprov"/> can run.</summary>
        public void SetLlmDelegate(NpcForgeImprovLlmDelegate del)
        {
            _llm = del;
        }

        /// <summary>Compose the final system prompt for a query without
        /// making an LLM call. Exposed so game code or tests can inspect
        /// exactly what would be sent.</summary>
        public string ComposeSystemPrompt(string query)
        {
            if (_ctx == null) return string.Empty;
            var chunks = RetrieveLoreChunks(query, _ctx.world_bible ?? "", topKLore);
            var sb = new StringBuilder();
            sb.AppendLine(_ctx.character_sheet_block?.TrimEnd() ?? "");
            sb.AppendLine();
            if (chunks.Count > 0)
            {
                sb.AppendLine("LORE SNIPPETS (authoritative — do not invent facts outside these):");
                foreach (var c in chunks)
                {
                    sb.AppendLine($"[{c.source}]");
                    sb.AppendLine(c.text);
                    sb.AppendLine();
                }
            }
            else
            {
                sb.AppendLine("LORE SNIPPETS: (none retrieved; ground your reply only in your character sheet)");
                sb.AppendLine();
            }
            sb.AppendLine(_ctx.rules_block?.TrimEnd() ?? "");
            return sb.ToString().TrimEnd() + "\n";
        }

        /// <summary>Fire-and-forget query. Parses the delegate's response
        /// and emits onReplyReceived / onError. Game code wires these
        /// events to dialogue UI.</summary>
        public async void RequestImprov(string query, CancellationToken ct = default)
        {
            if (!IsReady)
            {
                string reason = _ctx == null ? "no context loaded" : "no LLM delegate set";
                onError?.Invoke(reason);
                return;
            }
            string systemPrompt = ComposeSystemPrompt(query);
            string raw;
            try
            {
                raw = await _llm(systemPrompt, query, ct);
            }
            catch (Exception ex)
            {
                onError?.Invoke($"delegate threw: {ex.Message}");
                return;
            }
            var reply = ParseReply(raw);
            if (reply == null)
            {
                onError?.Invoke("failed to parse ImprovReply JSON from delegate");
                return;
            }
            onReplyReceived?.Invoke(reply);
        }

        // ---------------------------------------------------------------
        // Retrieval — port of improv.retrieve_lore_chunks
        // ---------------------------------------------------------------

        public struct LoreChunk
        {
            public string text;
            public string source;
            public float score;
        }

        private static readonly Regex _tokenRe = new Regex(
            @"[a-z0-9][a-z0-9\-']*", RegexOptions.Compiled);

        private static readonly HashSet<string> _stopwords = new HashSet<string>
        {
            "the","a","an","and","or","but","if","so","of","to","in",
            "on","at","by","for","from","with","as","is","was","are",
            "were","be","been","being","have","has","had","do","does",
            "did","it","its","this","that","these","those","i","you",
            "he","she","they","we","me","him","her","them","us","my",
            "your","his","their","our","what","which","who","whom",
            "where","when","why","how","all","any","some","no","not",
            "yes","too","very","just","also",
        };

        public static List<string> Tokens(string text)
        {
            var result = new List<string>();
            if (string.IsNullOrEmpty(text)) return result;
            foreach (Match m in _tokenRe.Matches(text.ToLowerInvariant()))
            {
                string w = m.Value;
                if (w.Length < 2) continue;
                if (_stopwords.Contains(w)) continue;
                result.Add(w);
            }
            return result;
        }

        /// <summary>Paragraph-split the bundle on blank lines.</summary>
        public static List<LoreChunk> SplitIntoChunks(
            string bundle, string sourcePrefix = "lore")
        {
            var result = new List<LoreChunk>();
            if (string.IsNullOrWhiteSpace(bundle)) return result;
            string norm = bundle.Replace("\r\n", "\n").Trim();
            string[] paras = Regex.Split(norm, @"\n\s*\n+");
            for (int i = 0; i < paras.Length; i++)
            {
                string p = paras[i].Trim();
                if (p.Length == 0) continue;
                result.Add(new LoreChunk
                {
                    text = p,
                    source = $"{sourcePrefix}#p{i}",
                    score = 0f,
                });
            }
            return result;
        }

        /// <summary>IDF-weighted token overlap against paragraph chunks.
        /// When the query has no scorable tokens or no chunks match,
        /// returns the first topK chunks so the LLM still has some
        /// grounding.</summary>
        public static List<LoreChunk> RetrieveLoreChunks(
            string query, string bundle, int topK, string sourcePrefix = "lore")
        {
            var chunks = SplitIntoChunks(bundle, sourcePrefix);
            if (chunks.Count == 0) return chunks;

            var queryTokens = Tokens(query);
            if (queryTokens.Count == 0)
                return chunks.GetRange(0, Math.Min(topK, chunks.Count));

            // Per-chunk token sets + document frequency table.
            var chunkTokens = new List<HashSet<string>>(chunks.Count);
            var df = new Dictionary<string, int>();
            foreach (var c in chunks)
            {
                var set = new HashSet<string>(Tokens(c.text));
                chunkTokens.Add(set);
                foreach (var t in set)
                    df[t] = df.TryGetValue(t, out int v) ? v + 1 : 1;
            }
            int n = chunks.Count;

            var scored = new List<LoreChunk>();
            for (int i = 0; i < chunks.Count; i++)
            {
                float score = 0f;
                foreach (var qt in queryTokens)
                {
                    if (chunkTokens[i].Contains(qt))
                    {
                        int dfq = df.TryGetValue(qt, out int d) ? d : 0;
                        score += Mathf.Log((n + 1f) / (dfq + 1f));
                    }
                }
                if (score > 0f)
                {
                    var c = chunks[i];
                    c.score = score;
                    scored.Add(c);
                }
            }
            if (scored.Count == 0)
                return chunks.GetRange(0, Math.Min(topK, chunks.Count));

            scored.Sort((a, b) => b.score.CompareTo(a.score));
            return scored.GetRange(0, Math.Min(topK, scored.Count));
        }

        // ---------------------------------------------------------------
        // Reply parsing — tolerates fenced code blocks the LLM sometimes
        // wraps JSON in.
        // ---------------------------------------------------------------

        public static NpcForgeImprovReply ParseReply(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw)) return null;
            string cleaned = raw.Trim();
            // Strip ```json fences if present.
            if (cleaned.StartsWith("```"))
            {
                int firstNewline = cleaned.IndexOf('\n');
                if (firstNewline > 0) cleaned = cleaned.Substring(firstNewline + 1);
                int endFence = cleaned.LastIndexOf("```", StringComparison.Ordinal);
                if (endFence >= 0) cleaned = cleaned.Substring(0, endFence);
                cleaned = cleaned.Trim();
            }
            try
            {
                var reply = JsonUtility.FromJson<NpcForgeImprovReply>(cleaned);
                if (reply == null || string.IsNullOrEmpty(reply.text)) return null;
                return reply;
            }
            catch
            {
                return null;
            }
        }
    }
}
