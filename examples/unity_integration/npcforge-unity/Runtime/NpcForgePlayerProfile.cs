// NpcForgePlayerProfile.cs
//
// Runtime mirror of npcforge's Python player_profile module (v0.13.0).
// Tracks how the player talks — not what they say — so observer NPCs
// can notice patterns across many scenes.
//
// Typical flow:
//   1. Gameplay code records memory events via NpcForgeMemoryStore.Record.
//   2. For every event with a known event_type, it also calls
//      NpcForgePlayerProfile.RegisterEvent(eventType) so the axes
//      update in lockstep.
//   3. The profile persists to Application.persistentDataPath under
//      a known filename so npcforge's Python side can import the
//      same file at generation time (names match — both sides read
//      <name>_player_profile.json).
//   4. Observer NPCs (wired via NpcForgeImprovClient + a PlayerProfile
//      reference) get the summary block in their improv prompts.
//
// JSON layout is byte-compatible with Python's PlayerProfile so one
// file drives both. Deltas live in code (DefaultAxisDeltas) — edit in
// both places if you're customising.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    [Serializable]
    public class NpcForgeProfileAxis
    {
        public string key;
        public float value;
    }

    /// <summary>Named trait tiers for UI colour coding. Not used by the
    /// summariser — the LLM reads raw weights.</summary>
    public enum PlayerTraitBand
    {
        None,       // < 0.10
        Hint,       // < 0.25
        Notable,    // < 0.50
        Dominant,   // >= 0.50
    }

    public class NpcForgePlayerProfile : MonoBehaviour
    {
        [Tooltip("Filename under Application.persistentDataPath.")]
        [SerializeField] private string fileName = "npcforge_player_profile.json";

        [Tooltip("Auto-save after every RegisterEvent call.")]
        [SerializeField] private bool autoSave = true;

        [Tooltip("Load from the configured path on Start().")]
        [SerializeField] private bool autoLoadOnStart = true;

        [SerializeField] private int updatedAtTurn;
        [SerializeField] private List<NpcForgeProfileAxis> axes
            = new List<NpcForgeProfileAxis>();

        [Header("Events")]
        /// <summary>Fires after every axis change. Payload is (axisKey, newValue).</summary>
        public UnityEvent<string, float> onAxisChanged
            = new UnityEvent<string, float>();

        public string FullPath
            => Path.Combine(Application.persistentDataPath, fileName);

        // ---------------------------------------------------------------
        // Default axis deltas — mirror Python's DEFAULT_AXIS_DELTAS.
        // Edit in both places when customising.
        // ---------------------------------------------------------------

        public static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, float>>
            DefaultAxisDeltas = new Dictionary<string, IReadOnlyDictionary<string, float>>
        {
            ["threat"] = new Dictionary<string, float> { ["aggressive"] = +0.20f },
            ["threaten_for_info"] = new Dictionary<string, float>
                { ["aggressive"] = +0.15f, ["curious"] = +0.05f },
            ["intimidate"] = new Dictionary<string, float> { ["aggressive"] = +0.15f },
            ["faction_harmed"] = new Dictionary<string, float>
                { ["aggressive"] = +0.10f, ["loyal"] = -0.10f },
            ["player_lied"] = new Dictionary<string, float>
                { ["deceptive"] = +0.15f, ["loyal"] = -0.05f },

            ["gift_given"] = new Dictionary<string, float>
                { ["patient"] = +0.10f, ["loyal"] = +0.05f },
            ["barter"] = new Dictionary<string, float> { ["patient"] = +0.05f },
            ["offer_help"] = new Dictionary<string, float> { ["patient"] = +0.10f },
            ["confess_vulnerability"] = new Dictionary<string, float>
                { ["patient"] = +0.10f, ["theatrical"] = +0.05f },
            ["secret_shared"] = new Dictionary<string, float>
                { ["patient"] = +0.10f, ["loyal"] = +0.10f },

            ["faction_helped"] = new Dictionary<string, float> { ["loyal"] = +0.15f },

            ["ask_about_npc_other"] = new Dictionary<string, float> { ["curious"] = +0.10f },
            ["improv_query"] = new Dictionary<string, float> { ["curious"] = +0.05f },
            ["ask_about_local_events"] = new Dictionary<string, float> { ["curious"] = +0.05f },
            ["ask_about_locket"] = new Dictionary<string, float> { ["curious"] = +0.10f },

            ["flirt"] = new Dictionary<string, float> { ["theatrical"] = +0.15f },
            ["dramatic_entrance"] = new Dictionary<string, float> { ["theatrical"] = +0.15f },
        };

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public int UpdatedAtTurn => updatedAtTurn;
        public IReadOnlyList<NpcForgeProfileAxis> Axes => axes;

        private void Start()
        {
            if (autoLoadOnStart) Load();
        }

        public float Get(string axis)
        {
            if (string.IsNullOrEmpty(axis)) return 0f;
            for (int i = 0; i < axes.Count; i++)
                if (axes[i].key == axis) return axes[i].value;
            return 0f;
        }

        /// <summary>Apply one event's deltas to this profile. Unknown event
        /// types are silent no-ops so the memory store can record any
        /// tag without breaking the profile.</summary>
        public void RegisterEvent(string eventType, int turn = -1)
        {
            if (!DefaultAxisDeltas.TryGetValue(eventType, out var deltas))
                return;
            foreach (var pair in deltas)
            {
                float next = Mathf.Clamp01(Get(pair.Key) + pair.Value);
                SetAxisInternal(pair.Key, next);
            }
            if (turn > updatedAtTurn) updatedAtTurn = turn;
            if (autoSave) Save();
        }

        /// <summary>Directly set an axis value. Clamped to [0, 1]. Fires
        /// onAxisChanged. Useful for scripted demos, cheats, or
        /// designer previews.</summary>
        public void SetAxis(string axisKey, float value)
        {
            if (string.IsNullOrEmpty(axisKey)) return;
            SetAxisInternal(axisKey, Mathf.Clamp01(value));
            if (autoSave) Save();
        }

        public PlayerTraitBand BandFor(string axis)
        {
            float v = Get(axis);
            if (v < 0.10f) return PlayerTraitBand.None;
            if (v < 0.25f) return PlayerTraitBand.Hint;
            if (v < 0.50f) return PlayerTraitBand.Notable;
            return PlayerTraitBand.Dominant;
        }

        /// <summary>Top-N traits above ``minWeight``, highest first.
        /// Mirrors Python's PlayerProfile.top_traits so both runtimes
        /// agree on which axes are 'observable'.</summary>
        public List<NpcForgeProfileAxis> TopTraits(int n = 3, float minWeight = 0.25f)
        {
            var list = new List<NpcForgeProfileAxis>();
            foreach (var a in axes)
                if (a.value >= minWeight) list.Add(a);
            list.Sort((x, y) => y.value.CompareTo(x.value));
            if (n > 0 && list.Count > n) list = list.GetRange(0, n);
            return list;
        }

        public void Clear()
        {
            axes.Clear();
            updatedAtTurn = 0;
            if (autoSave) Save();
        }

        // ---------------------------------------------------------------
        // Persistence — byte-compatible with Python PlayerProfile
        // ---------------------------------------------------------------

        /// <summary>JSON shape of the persisted profile. Public so tests
        /// can verify parse output without InternalsVisibleTo gymnastics.</summary>
        [Serializable]
        public class Dto
        {
            public string schema_version = "1";
            public int updated_at_turn;
            public List<NpcForgeProfileAxis> axes = new List<NpcForgeProfileAxis>();
        }

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Application.persistentDataPath);
                File.WriteAllText(FullPath, BuildJson());
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgePlayerProfile] save failed: {ex.Message}");
            }
        }

        public void Load()
        {
            if (!File.Exists(FullPath)) return;
            try
            {
                string json = File.ReadAllText(FullPath);
                var dto = ParseJson(json);
                if (dto == null) return;
                updatedAtTurn = dto.updated_at_turn;
                axes = dto.axes ?? new List<NpcForgeProfileAxis>();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgePlayerProfile] load failed: {ex.Message}");
            }
        }

        // ---------------------------------------------------------------
        // Observer summary — same shape as Python summarize_for_observer
        // ---------------------------------------------------------------

        private static readonly IReadOnlyDictionary<string, string> _axisProse
            = new Dictionary<string, string>
        {
            ["aggressive"] = "takes the aggressive line with you — pressure, not persuasion",
            ["patient"] = "tends to approach patiently — gifts, listening, time",
            ["deceptive"] = "lies to you when it suits them",
            ["curious"] = "asks more than they're asked — probes",
            ["theatrical"] = "plays up the drama when they speak",
            ["loyal"] = "has backed the people you've asked them to back",
            ["disloyal"] = "has stepped away from the people you trusted them with",
        };

        public string SummarizeForObserver(int maxTraits = 3, float minWeight = 0.25f)
        {
            var traits = TopTraits(maxTraits, minWeight);
            if (traits.Count == 0) return string.Empty;
            var sb = new System.Text.StringBuilder();
            sb.AppendLine(
                "Player pattern (observed across prior encounters; you notice these "
                + "things about them because your role asks it of you):");
            foreach (var t in traits)
            {
                string prose = _axisProse.TryGetValue(t.key, out var p)
                    ? p : $"tends to be {t.key}";
                sb.AppendLine($"- {t.key} ({t.value:F1}): {prose}");
            }
            sb.Append(
                "Reference the pattern only if it fits naturally. Do not list "
                + "traits, do not quote numbers, and do not perform-the-observation.");
            return sb.ToString();
        }

        // ---------------------------------------------------------------
        // Internals
        // ---------------------------------------------------------------

        private void SetAxisInternal(string axisKey, float clampedValue)
        {
            for (int i = 0; i < axes.Count; i++)
            {
                if (axes[i].key == axisKey)
                {
                    axes[i].value = clampedValue;
                    onAxisChanged?.Invoke(axisKey, clampedValue);
                    return;
                }
            }
            axes.Add(new NpcForgeProfileAxis { key = axisKey, value = clampedValue });
            onAxisChanged?.Invoke(axisKey, clampedValue);
        }

        // JsonUtility handles list-of-struct just fine; we only need
        // a tiny DTO shim for the snake_case field names Python emits.
        public string BuildJson()
        {
            // Emit Python's dict-shape directly so one file round-trips
            // between engines. JsonUtility would serialise axes as a list
            // of {key, value} objects — incompatible with Python's
            // {"axes": {"aggressive": 0.55}} format. Hand-build instead
            // (the schema is small enough to not warrant a JSON lib).
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("{");
            sb.AppendLine("  \"schema_version\": \"1\",");
            sb.AppendLine($"  \"updated_at_turn\": {updatedAtTurn},");
            sb.Append("  \"axes\": {");
            for (int i = 0; i < axes.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.AppendLine();
                // Use invariant format so non-English locales don't emit
                // comma decimals.
                string v = axes[i].value.ToString("G17",
                    System.Globalization.CultureInfo.InvariantCulture);
                sb.Append($"    \"{Escape(axes[i].key)}\": {v}");
            }
            if (axes.Count > 0) sb.AppendLine();
            sb.Append("  }");
            sb.AppendLine();
            sb.Append("}");
            return sb.ToString();
        }

        private static string Escape(string s)
        {
            return s == null ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }

        // Python's PlayerProfile emits {"axes": {"aggressive": 0.55,
        // "curious": 0.15}} — a DICT, not a list. JsonUtility can't parse
        // dicts, so we hand-convert.
        public static Dto ParseJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return null;
            var dto = new Dto();

            // Extract updated_at_turn (int, easy).
            var turnMatch = System.Text.RegularExpressions.Regex.Match(
                json, @"""updated_at_turn""\s*:\s*(\d+)");
            if (turnMatch.Success)
                int.TryParse(turnMatch.Groups[1].Value, out dto.updated_at_turn);

            // Extract the axes dict body.
            var axesMatch = System.Text.RegularExpressions.Regex.Match(
                json, @"""axes""\s*:\s*\{([^}]*)\}",
                System.Text.RegularExpressions.RegexOptions.Singleline);
            if (axesMatch.Success)
            {
                string body = axesMatch.Groups[1].Value;
                // Each entry is "key": number
                var entries = System.Text.RegularExpressions.Regex.Matches(
                    body, @"""([^""]+)""\s*:\s*([\-0-9.eE]+)");
                foreach (System.Text.RegularExpressions.Match m in entries)
                {
                    if (float.TryParse(m.Groups[2].Value,
                        System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture,
                        out float v))
                    {
                        dto.axes.Add(new NpcForgeProfileAxis
                        {
                            key = m.Groups[1].Value,
                            value = v,
                        });
                    }
                }
            }
            return dto;
        }
    }
}
