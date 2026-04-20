// NpcForgeQuestTracker.cs
//
// Runtime mirror of Python's v0.21.0 quest module. Per-quest current-
// stage cursor with JSON save/load that round-trips with the Python
// side's quest_state.json format. The quest definitions (stage lists,
// labels, descriptions, known_to filters) are authored in
// <demo-dir>/quests.yaml on the Python side; this component stores
// only the runtime state.
//
// Gameplay flow:
// - Call SetStage / Advance when narrative beats fire.
// - onStageChanged UnityEvent fires on every transition so UI,
//   music, and other systems can react.
// - Before improv, call SummarizeForPrompt(npcId) to render the
//   block Python's summarize_active_quests would emit for this NPC
//   (respecting known_to visibility).

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
    public class NpcForgeQuestStage
    {
        public string id;
        public string label;
        public string description = "";
        public List<string> known_to = new List<string>();
    }

    [Serializable]
    public class NpcForgeQuest
    {
        public string id;
        public string name;
        public string description = "";
        public List<NpcForgeQuestStage> stages = new List<NpcForgeQuestStage>();

        public int StageIndex(string stageId)
        {
            for (int i = 0; i < stages.Count; i++)
                if (stages[i].id == stageId) return i;
            return -1;
        }
    }

    [Serializable]
    public class NpcForgeQuestsConfig
    {
        public List<NpcForgeQuest> quests = new List<NpcForgeQuest>();

        public NpcForgeQuest ById(string questId)
        {
            foreach (var q in quests)
                if (q.id == questId) return q;
            return null;
        }
    }

    public class NpcForgeQuestTracker : MonoBehaviour
    {
        [Tooltip("Quest definitions. Usually populated at runtime via " +
                 "ImportConfigJson (from the Python export) or authored " +
                 "in the Inspector for quick prototypes.")]
        [SerializeField]
        private NpcForgeQuestsConfig config = new NpcForgeQuestsConfig();

        [Tooltip("Filename under Application.persistentDataPath. Matches " +
                 "Python's demo-dir/quest_state.json naming when you copy " +
                 "it in.")]
        [SerializeField] private string fileName = "npcforge_quest_state.json";

        [Tooltip("Auto-save after SetStage / Advance.")]
        [SerializeField] private bool autoSave = true;

        [Tooltip("Load from the configured path on Start().")]
        [SerializeField] private bool autoLoadOnStart = true;

        // Current stage id per quest (list-of-entries because JsonUtility
        // can't serialise Dictionary).
        [Serializable]
        public class CurrentEntry
        {
            public string quest_id;
            public string stage_id;
        }

        [SerializeField] private List<CurrentEntry> currentStages
            = new List<CurrentEntry>();

        [Header("Events")]
        /// <summary>Fires on every stage transition. Payload is
        /// (questId, oldStageId, newStageId). Old stage id is empty
        /// string for a freshly-started quest.</summary>
        public UnityEvent<string, string, string> onStageChanged
            = new UnityEvent<string, string, string>();

        public string FullPath
            => Path.Combine(Application.persistentDataPath, fileName);

        public NpcForgeQuestsConfig Config => config;

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        private void Start()
        {
            if (autoLoadOnStart) Load();
        }

        public string CurrentStageId(string questId)
        {
            foreach (var e in currentStages)
                if (e.quest_id == questId) return e.stage_id;
            return null;
        }

        public void SetStage(string questId, string stageId)
        {
            var quest = config.ById(questId);
            if (quest == null)
                throw new ArgumentException(
                    $"Unknown quest '{questId}'", nameof(questId));
            if (quest.StageIndex(stageId) < 0)
                throw new ArgumentException(
                    $"Quest '{questId}' has no stage '{stageId}'",
                    nameof(stageId));

            string oldId = CurrentStageId(questId) ?? "";
            bool found = false;
            for (int i = 0; i < currentStages.Count; i++)
            {
                if (currentStages[i].quest_id == questId)
                {
                    currentStages[i].stage_id = stageId;
                    found = true;
                    break;
                }
            }
            if (!found)
                currentStages.Add(new CurrentEntry {
                    quest_id = questId, stage_id = stageId,
                });

            if (oldId != stageId) onStageChanged?.Invoke(questId, oldId, stageId);
            if (autoSave) Save();
        }

        /// <summary>Advance to the next stage. Returns the new stage id
        /// or null when already at the last stage.</summary>
        public string Advance(string questId)
        {
            var quest = config.ById(questId);
            if (quest == null)
                throw new ArgumentException(
                    $"Unknown quest '{questId}'", nameof(questId));
            string current = CurrentStageId(questId);
            if (current == null)
            {
                SetStage(questId, quest.stages[0].id);
                return quest.stages[0].id;
            }
            int idx = quest.StageIndex(current);
            if (idx >= quest.stages.Count - 1) return null;
            string next = quest.stages[idx + 1].id;
            SetStage(questId, next);
            return next;
        }

        public bool IsAtOrPast(string questId, string stageId)
        {
            var quest = config.ById(questId);
            if (quest == null) return false;
            string current = CurrentStageId(questId);
            if (current == null) return false;
            int ci = quest.StageIndex(current);
            int ti = quest.StageIndex(stageId);
            if (ci < 0 || ti < 0) return false;
            return ci >= ti;
        }

        /// <summary>Quests with a started stage whose current stage is
        /// visible to ``npcId`` (empty known_to = everyone sees).</summary>
        public List<(NpcForgeQuest quest, NpcForgeQuestStage stage)>
            StagesVisibleTo(string npcId)
        {
            var result = new List<(NpcForgeQuest, NpcForgeQuestStage)>();
            foreach (var entry in currentStages)
            {
                var q = config.ById(entry.quest_id);
                if (q == null) continue;
                int idx = q.StageIndex(entry.stage_id);
                if (idx < 0) continue;
                var stage = q.stages[idx];
                if (stage.known_to != null && stage.known_to.Count > 0)
                {
                    if (!stage.known_to.Contains(npcId)) continue;
                }
                result.Add((q, stage));
            }
            return result;
        }

        /// <summary>Produce the prompt block matching Python's
        /// summarize_active_quests. Empty string when the NPC has no
        /// visible active quests.</summary>
        public string SummarizeForPrompt(string npcId)
        {
            var visible = StagesVisibleTo(npcId);
            if (visible.Count == 0) return string.Empty;
            var sb = new StringBuilder();
            sb.AppendLine(
                "Active quests (what the player is currently holding; "
                + "reference them naturally when relevant, never recite "
                + "the stage id or quest id aloud):");
            foreach (var (q, stage) in visible)
            {
                sb.AppendLine($"- {q.name}: {stage.label}");
                if (!string.IsNullOrWhiteSpace(stage.description))
                    sb.AppendLine($"    {stage.description.Trim()}");
            }
            return sb.ToString().TrimEnd();
        }

        public void ImportConfigJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                config = new NpcForgeQuestsConfig();
                return;
            }
            config = JsonUtility.FromJson<NpcForgeQuestsConfig>(json)
                    ?? new NpcForgeQuestsConfig();
        }

        public void Clear()
        {
            currentStages.Clear();
            if (autoSave) Save();
        }

        // ---------------------------------------------------------------
        // Persistence — byte-compatible with Python QuestTracker.
        //
        // Python writes:
        //   { "schema_version": "1",
        //     "current_stages": {"recover_locket": "accepted"} }
        //
        // JsonUtility can't parse dict; we hand-write and regex-read
        // (same pattern NpcForgePlayerProfile uses).
        // ---------------------------------------------------------------

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Application.persistentDataPath);
                File.WriteAllText(FullPath, BuildStateJson());
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgeQuestTracker] save failed: {ex.Message}");
            }
        }

        public void Load()
        {
            if (!File.Exists(FullPath)) return;
            try
            {
                currentStages = ParseStateJson(File.ReadAllText(FullPath));
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[NpcForgeQuestTracker] load failed: {ex.Message}");
            }
        }

        public string BuildStateJson()
        {
            var sb = new StringBuilder();
            sb.AppendLine("{");
            sb.AppendLine("  \"schema_version\": \"1\",");
            sb.Append("  \"current_stages\": {");
            for (int i = 0; i < currentStages.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.AppendLine();
                sb.Append($"    \"{Escape(currentStages[i].quest_id)}\": " +
                          $"\"{Escape(currentStages[i].stage_id)}\"");
            }
            if (currentStages.Count > 0) sb.AppendLine();
            sb.Append("  }");
            sb.AppendLine();
            sb.Append("}");
            return sb.ToString();
        }

        public static List<CurrentEntry> ParseStateJson(string json)
        {
            var result = new List<CurrentEntry>();
            if (string.IsNullOrWhiteSpace(json)) return result;
            var objMatch = Regex.Match(
                json,
                "\"current_stages\"\\s*:\\s*\\{([^}]*)\\}",
                RegexOptions.Singleline);
            if (!objMatch.Success) return result;
            string body = objMatch.Groups[1].Value;
            var entries = Regex.Matches(
                body, "\"([^\"]+)\"\\s*:\\s*\"((?:\\\\\"|[^\"])*)\"");
            foreach (Match m in entries)
            {
                result.Add(new CurrentEntry {
                    quest_id = m.Groups[1].Value,
                    stage_id = Unescape(m.Groups[2].Value),
                });
            }
            return result;
        }

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }

        private static string Unescape(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            return s.Replace("\\\"", "\"").Replace("\\\\", "\\");
        }
    }
}
