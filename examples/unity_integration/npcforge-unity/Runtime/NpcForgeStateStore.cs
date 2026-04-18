// NpcForgeStateStore.cs
//
// Friendlier wrapper around Yarn Spinner's VariableStorage. Exposes
// typed getters and setters plus an OnVariableChanged event so game code
// can react to npcforge's declared project variables without writing
// boilerplate around the Yarn API.
//
// Typical use:
//   stateStore.SetString("$time_of_day", "dusk");
//   stateStore.SetNumber("$disposition_mira", 42);
//   stateStore.OnVariableChanged += (name, value) => Debug.Log($"{name} = {value}");
//
// Inspect the latest known values in the Editor via the Npcforge State
// Inspector window (Window → npcforge → State Inspector).

using System;
using System.Collections.Generic;
using UnityEngine;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge
{
    /// <summary>Fired whenever a variable is read or written through this store.</summary>
    public delegate void NpcForgeVariableChanged(string name, object value);

    public class NpcForgeStateStore : MonoBehaviour
    {
#if NPCFORGE_HAS_YARN
        [SerializeField] private DialogueRunner dialogueRunner;
#endif

        /// <summary>Snapshot of the most recent value we read or wrote for
        /// each variable. Populated lazily; used by the Editor's State
        /// Inspector window to show something even before Yarn has run.</summary>
        private readonly Dictionary<string, object> _lastSeen = new Dictionary<string, object>();

        public event NpcForgeVariableChanged OnVariableChanged;

        /// <summary>Read-only snapshot of the variables this store has
        /// observed. Safe to iterate from Editor code.</summary>
        public IReadOnlyDictionary<string, object> Snapshot => _lastSeen;

        // ---------------------------------------------------------------
        // String variables (enum project variables like $time_of_day)
        // ---------------------------------------------------------------

        public string GetString(string name, string fallback = "")
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null
                && dialogueRunner.VariableStorage.TryGetValue(name, out string v))
            {
                _lastSeen[name] = v;
                return v;
            }
#endif
            // Fall back to the most recent value we wrote for this name.
            // Useful for Edit-mode tests and for scenes that use the store
            // without a DialogueRunner attached yet.
            if (_lastSeen.TryGetValue(name, out object cached) && cached is string cs)
                return cs;
            return fallback;
        }

        public void SetString(string name, string value)
        {
            // Always update the snapshot + fire the event — even when no
            // DialogueRunner is wired. The previous "early return" meant
            // editors / tests / headless scenes silently dropped writes.
#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null)
            {
                dialogueRunner.VariableStorage.SetValue(name, value);
            }
#endif
            _lastSeen[name] = value;
            OnVariableChanged?.Invoke(name, value);
        }

        // ---------------------------------------------------------------
        // Numeric variables (int / float — Yarn stores numbers as float)
        // ---------------------------------------------------------------

        public float GetNumber(string name, float fallback = 0f)
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null
                && dialogueRunner.VariableStorage.TryGetValue(name, out float v))
            {
                _lastSeen[name] = v;
                return v;
            }
#endif
            if (_lastSeen.TryGetValue(name, out object cached) && cached is float cf)
                return cf;
            return fallback;
        }

        public void SetNumber(string name, float value)
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null)
            {
                dialogueRunner.VariableStorage.SetValue(name, value);
            }
#endif
            _lastSeen[name] = value;
            OnVariableChanged?.Invoke(name, value);
        }

        /// <summary>Convenience: add a delta to a numeric variable, clamped to
        /// ``[min, max]``. Returns the new value.</summary>
        public float AddClamped(string name, float delta, float min = float.MinValue, float max = float.MaxValue)
        {
            float next = Mathf.Clamp(GetNumber(name) + delta, min, max);
            SetNumber(name, next);
            return next;
        }

        // ---------------------------------------------------------------
        // Bool variables
        // ---------------------------------------------------------------

        public bool GetBool(string name, bool fallback = false)
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null
                && dialogueRunner.VariableStorage.TryGetValue(name, out bool v))
            {
                _lastSeen[name] = v;
                return v;
            }
#endif
            if (_lastSeen.TryGetValue(name, out object cached) && cached is bool cb)
                return cb;
            return fallback;
        }

        public void SetBool(string name, bool value)
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner != null)
            {
                dialogueRunner.VariableStorage.SetValue(name, value);
            }
#endif
            _lastSeen[name] = value;
            OnVariableChanged?.Invoke(name, value);
        }

        // ---------------------------------------------------------------
        // Bulk helpers
        // ---------------------------------------------------------------

        /// <summary>Apply a dictionary of {name → value} updates. Types are
        /// dispatched by the value's .NET type.</summary>
        public void SetMany(IDictionary<string, object> updates)
        {
            if (updates == null) return;
            foreach (var kv in updates)
            {
                switch (kv.Value)
                {
                    case string s: SetString(kv.Key, s); break;
                    case bool b: SetBool(kv.Key, b); break;
                    case float f: SetNumber(kv.Key, f); break;
                    case int i: SetNumber(kv.Key, i); break;
                    case double d: SetNumber(kv.Key, (float)d); break;
                    default:
                        Debug.LogWarning($"[NpcForgeStateStore] Unsupported type for {kv.Key}: {kv.Value?.GetType()}");
                        break;
                }
            }
        }
    }
}
