// NpcForgeSaveLoad.cs
//
// Minimal save/load for every Yarn variable npcforge cares about:
// disposition_<npc>, player_state, time_of_day, knows_*, visited_*,
// plus whatever the user has declared via variables.yaml.
//
// Format is plain JSON (JsonUtility-compatible) so saves stay diff-friendly
// and easy to inspect. One file per slot under Application.persistentDataPath.
//
// Why a MonoBehaviour (not a ScriptableObject)? A MonoBehaviour is easy to
// drop in the scene and wire to UI buttons via UnityEvents without writing
// any code. A ScriptableObject would still need a driver component anyway.
//
// How we enumerate variables: Yarn Spinner doesn't expose a universal
// "give me every declared variable" API, but every version has some
// form of ``GetAllVariables`` on ``InMemoryVariableStorage`` (the
// default store). We call it via reflection so the package doesn't have
// to pin a specific Yarn Spinner API version.

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;
using UnityEngine.Events;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge
{
    /// <summary>
    /// Drop onto a GameObject in the scene, wire the DialogueRunner and
    /// (optionally) an NpcForgeStateStore, and call <see cref="Save"/> /
    /// <see cref="Load"/> from UI buttons or game code.
    /// </summary>
    public class NpcForgeSaveLoad : MonoBehaviour
    {
#if NPCFORGE_HAS_YARN
        [Tooltip("Required — we need the DialogueRunner's VariableStorage " +
                 "to round-trip every declared variable, not just the ones " +
                 "NpcForgeStateStore has observed.")]
        [SerializeField] private DialogueRunner dialogueRunner;
#endif

        [Tooltip("Optional. If assigned, loaded values flow through this " +
                 "store's SetMany so OnVariableChanged listeners fire.")]
        [SerializeField] private NpcForgeStateStore stateStore;

        [Tooltip("Filename under Application.persistentDataPath.")]
        [SerializeField] private string fileName = "npcforge_save.json";

        [Tooltip("Optional slot suffix — set to 'slot2' for a second save, etc.")]
        [SerializeField] private string slot = "default";

        [Header("Events")]
        public UnityEvent onSaved;
        public UnityEvent onLoaded;
        public UnityEvent onLoadMissing;

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public string FullPath
        {
            get
            {
                string name = string.IsNullOrEmpty(slot) || slot == "default"
                    ? fileName
                    : Path.GetFileNameWithoutExtension(fileName) + "_" + slot +
                      Path.GetExtension(fileName);
                return Path.Combine(Application.persistentDataPath, name);
            }
        }

        /// <summary>Serialize every variable we can see and write to disk.</summary>
        public void Save()
        {
            var dto = SerializeAll();
            string json = JsonUtility.ToJson(dto, prettyPrint: true);
            Directory.CreateDirectory(Application.persistentDataPath);
            File.WriteAllText(FullPath, json);
            Debug.Log($"[NpcForgeSave] Saved {dto.entries.Count} variables to {FullPath}");
            onSaved?.Invoke();
        }

        /// <summary>Load if a save exists; otherwise fire onLoadMissing.</summary>
        public void Load()
        {
            if (!File.Exists(FullPath))
            {
                Debug.Log($"[NpcForgeSave] No save at {FullPath}");
                onLoadMissing?.Invoke();
                return;
            }
            string json = File.ReadAllText(FullPath);
            var dto = JsonUtility.FromJson<SaveDto>(json);
            if (dto == null || dto.entries == null)
            {
                Debug.LogWarning($"[NpcForgeSave] Save file unreadable: {FullPath}");
                onLoadMissing?.Invoke();
                return;
            }
            Apply(dto);
            Debug.Log($"[NpcForgeSave] Loaded {dto.entries.Count} variables from {FullPath}");
            onLoaded?.Invoke();
        }

        /// <summary>Delete the current slot's save file (no prompt).</summary>
        public void DeleteSlot()
        {
            if (File.Exists(FullPath))
            {
                File.Delete(FullPath);
                Debug.Log($"[NpcForgeSave] Deleted {FullPath}");
            }
        }

        // ---------------------------------------------------------------
        // Serialization internals
        // ---------------------------------------------------------------

        [Serializable]
        public class SaveEntry
        {
            public string name;
            public string type;   // "string" | "float" | "bool"
            public string value;  // culture-invariant string form
        }

        [Serializable]
        public class SaveDto
        {
            public string schemaVersion = "1";
            public string savedAt = string.Empty;
            public List<SaveEntry> entries = new List<SaveEntry>();
        }

        private SaveDto SerializeAll()
        {
            var dto = new SaveDto
            {
                savedAt = DateTime.UtcNow.ToString("o", System.Globalization.CultureInfo.InvariantCulture),
            };
            foreach (var kv in CollectAllVariables())
            {
                var entry = new SaveEntry { name = kv.Key };
                switch (kv.Value)
                {
                    case string s: entry.type = "string"; entry.value = s; break;
                    case bool b: entry.type = "bool"; entry.value = b ? "true" : "false"; break;
                    case float f:
                        entry.type = "float";
                        entry.value = f.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
                        break;
                    case double d:
                        entry.type = "float";
                        entry.value = ((float)d).ToString("R", System.Globalization.CultureInfo.InvariantCulture);
                        break;
                    case int i:
                        entry.type = "float";
                        entry.value = i.ToString(System.Globalization.CultureInfo.InvariantCulture);
                        break;
                    default:
                        // Unknown type — skip rather than crash.
                        continue;
                }
                dto.entries.Add(entry);
            }
            return dto;
        }

        private void Apply(SaveDto dto)
        {
            var updates = new Dictionary<string, object>(dto.entries.Count);
            foreach (var e in dto.entries)
            {
                object v;
                switch (e.type)
                {
                    case "string": v = e.value; break;
                    case "bool":
                        v = string.Equals(e.value, "true", StringComparison.OrdinalIgnoreCase);
                        break;
                    case "float":
                        if (float.TryParse(e.value,
                            System.Globalization.NumberStyles.Float,
                            System.Globalization.CultureInfo.InvariantCulture,
                            out float f))
                        {
                            v = f;
                        }
                        else continue;
                        break;
                    default: continue;
                }
                updates[e.name] = v;
            }
            // Prefer the state store path so listeners fire; fall back to
            // writing directly to the DialogueRunner if no store is wired.
            if (stateStore != null)
            {
                stateStore.SetMany(updates);
            }
            else
            {
                WriteDirectlyToRunner(updates);
            }
        }

        private void WriteDirectlyToRunner(IDictionary<string, object> updates)
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner == null) return;
            foreach (var kv in updates)
            {
                switch (kv.Value)
                {
                    case string s: dialogueRunner.VariableStorage.SetValue(kv.Key, s); break;
                    case bool b: dialogueRunner.VariableStorage.SetValue(kv.Key, b); break;
                    case float f: dialogueRunner.VariableStorage.SetValue(kv.Key, f); break;
                }
            }
#endif
        }

        /// <summary>Enumerate every variable we can see. Source order:
        /// 1. VariableStorage.GetAllVariables() via reflection (the full
        ///    set, including declared-but-never-touched variables);
        /// 2. fall back to NpcForgeStateStore.Snapshot (observed only).
        /// </summary>
        private Dictionary<string, object> CollectAllVariables()
        {
            var result = new Dictionary<string, object>();

#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null && dialogueRunner.VariableStorage != null)
            {
                var store = dialogueRunner.VariableStorage;
                var method = store.GetType().GetMethod(
                    "GetAllVariables",
                    BindingFlags.Public | BindingFlags.Instance);
                if (method != null)
                {
                    try
                    {
                        // Signature: Tuple<Dictionary<string, float>,
                        //   Dictionary<string, string>, Dictionary<string, bool>> GetAllVariables()
                        var tuple = method.Invoke(store, null);
                        if (tuple != null)
                        {
                            MergeTupleVariable<float>(result, tuple, "Item1");
                            MergeTupleVariable<string>(result, tuple, "Item2");
                            MergeTupleVariable<bool>(result, tuple, "Item3");
                        }
                    }
                    catch (Exception ex)
                    {
                        Debug.LogWarning($"[NpcForgeSave] reflection call on " +
                                         $"VariableStorage.GetAllVariables failed: {ex.Message}");
                    }
                }
            }
#endif
            // Top up with whatever the StateStore has observed — catches
            // cases where VariableStorage reflection failed or the runner
            // wasn't assigned.
            if (stateStore != null)
            {
                foreach (var kv in stateStore.Snapshot)
                {
                    if (!result.ContainsKey(kv.Key)) result[kv.Key] = kv.Value;
                }
            }

            return result;
        }

        private static void MergeTupleVariable<T>(
            Dictionary<string, object> into, object tuple, string itemName)
        {
            // Yarn Spinner's GetAllVariables returns a C# ValueTuple whose
            // Item1/Item2/Item3 members are *fields*, not properties.
            // Older releases used System.Tuple with properties. Try field
            // first and fall back to property so we cover both shapes.
            object value = null;
            var field = tuple.GetType().GetField(itemName,
                BindingFlags.Public | BindingFlags.Instance);
            if (field != null)
            {
                value = field.GetValue(tuple);
            }
            else
            {
                var prop = tuple.GetType().GetProperty(itemName,
                    BindingFlags.Public | BindingFlags.Instance);
                if (prop != null) value = prop.GetValue(tuple);
            }
            if (!(value is IDictionary<string, T> dict)) return;
            foreach (var kv in dict)
            {
                into[kv.Key] = kv.Value;
            }
        }
    }
}
