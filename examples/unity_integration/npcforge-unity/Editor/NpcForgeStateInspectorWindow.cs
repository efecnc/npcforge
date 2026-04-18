// NpcForgeStateInspectorWindow.cs
//
// Live viewer for Yarn Spinner's VariableStorage during Play mode.
// Finds the first `NpcForgeDialogueController` or `DialogueRunner` in
// the active scene, polls its VariableStorage every few frames, and
// renders a table of {name, type, value, *edit*} — writers can tweak a
// variable and see the effect immediately in the running game without
// stopping Play.
//
// Outside Play mode we show the most recent values seen by any
// `NpcForgeStateStore` present in the scene (it keeps its own snapshot
// so Editor code can inspect even before Yarn has run).

using System.Collections.Generic;
using System.Reflection;
using UnityEditor;
using UnityEngine;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge.Editor
{
    public class NpcForgeStateInspectorWindow : EditorWindow
    {
        private Vector2 _scroll;
        private double _lastPollTime;
        private readonly Dictionary<string, object> _lastValues = new Dictionary<string, object>();

        [MenuItem("Tools/npcforge/State Inspector...", priority = 21)]
        public static void Open()
        {
            var wnd = GetWindow<NpcForgeStateInspectorWindow>();
            wnd.titleContent = new GUIContent("npcforge State");
            wnd.minSize = new Vector2(420, 340);
            wnd.Show();
        }

        private void OnEnable()
        {
            EditorApplication.update += OnEditorUpdate;
        }

        private void OnDisable()
        {
            EditorApplication.update -= OnEditorUpdate;
        }

        private void OnEditorUpdate()
        {
            // Poll at ~5 Hz in Play mode; otherwise only on focus / user action.
            if (!EditorApplication.isPlaying) return;
            if (EditorApplication.timeSinceStartup - _lastPollTime < 0.2) return;
            _lastPollTime = EditorApplication.timeSinceStartup;
            Poll();
            Repaint();
        }

        private void Poll()
        {
            _lastValues.Clear();

#if NPCFORGE_HAS_YARN
            // 1) Try every DialogueRunner in the scene.
            var runners = Object.FindObjectsOfType<DialogueRunner>();
            foreach (var runner in runners)
            {
                var storage = runner.VariableStorage;
                if (storage == null) continue;
                // VariableStorage has a .GetAllVariables() method in recent
                // Yarn Spinner releases; fall back to reflection if absent.
                TryReadAllVariables(storage, _lastValues);
            }
#endif

            // 2) Fold in whatever NpcForgeStateStore has observed so far.
            //    Zero-arg FindObjectsByType is the modern non-obsolete
            //    scene search — replaces Unity 2022's FindObjectsOfType
            //    and the short-lived sort-mode overload.
            foreach (var store in Object.FindObjectsByType<NpcForgeStateStore>(FindObjectsInactive.Exclude))
            {
                foreach (var kv in store.Snapshot)
                {
                    _lastValues[kv.Key] = kv.Value;
                }
            }
        }

        private static void TryReadAllVariables(object storage, Dictionary<string, object> into)
        {
            // Preferred modern Yarn API:
            //   Dictionary<string, float|bool|string> GetAllVariables()
            // Older APIs varied. Use reflection so the package stays
            // compatible without a hard version pin.
            var t = storage.GetType();
            var m = t.GetMethod("GetAllVariables", BindingFlags.Public | BindingFlags.Instance)
                 ?? t.GetMethod("GetVariables", BindingFlags.Public | BindingFlags.Instance);
            if (m == null) return;

            object result;
            try { result = m.Invoke(storage, null); }
            catch { return; }

            if (result is System.Collections.IDictionary dict)
            {
                foreach (System.Collections.DictionaryEntry entry in dict)
                {
                    if (entry.Key is string k) into[k] = entry.Value;
                }
                return;
            }

            // Some Yarn versions return three dictionaries via out params;
            // give up gracefully rather than maintain a branch for each.
        }

        private void OnGUI()
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                GUILayout.Label(
                    EditorApplication.isPlaying
                        ? "Live Yarn variables (polling 5 Hz)"
                        : "Play-mode viewer — enter Play to see live state",
                    EditorStyles.toolbarButton);
                if (GUILayout.Button("Refresh", EditorStyles.toolbarButton, GUILayout.Width(80)))
                {
                    Poll();
                }
            }

            if (_lastValues.Count == 0)
            {
                EditorGUILayout.HelpBox(
                    "No Yarn variables observed yet. In Play mode this window polls " +
                    "every DialogueRunner in the scene; out of Play mode it shows the " +
                    "most recent values tracked by NpcForgeStateStore components.",
                    MessageType.Info);
                return;
            }

            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                GUILayout.Label("Variable", EditorStyles.toolbarButton, GUILayout.Width(220));
                GUILayout.Label("Type", EditorStyles.toolbarButton, GUILayout.Width(70));
                GUILayout.Label("Value", EditorStyles.toolbarButton);
            }

            foreach (var kv in _lastValues)
            {
                DrawRow(kv.Key, kv.Value);
            }
            EditorGUILayout.EndScrollView();
        }

        private void DrawRow(string name, object value)
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.SelectableLabel(name, GUILayout.Width(220), GUILayout.Height(18));
                string type = value?.GetType()?.Name ?? "?";
                EditorGUILayout.LabelField(type, EditorStyles.miniLabel, GUILayout.Width(70));

                if (!EditorApplication.isPlaying)
                {
                    EditorGUILayout.SelectableLabel(FormatValue(value), GUILayout.Height(18));
                    return;
                }

                // Play mode — allow edits that flow back to VariableStorage
                // via any NpcForgeStateStore in the scene.
                EditRow(name, value);
            }
        }

        private void EditRow(string name, object value)
        {
            // FindAnyObjectByType is the modern scene-search API in
            // Unity 6 — it's ordering-independent (FindFirstObjectByType
            // was deprecated because it relied on instance-id ordering)
            // and fine here because we just need any one store to route
            // edits through.
            var store = Object.FindAnyObjectByType<NpcForgeStateStore>();

            if (value is float f)
            {
                float next = EditorGUILayout.FloatField(f);
                if (!Mathf.Approximately(next, f) && store != null)
                {
                    store.SetNumber(name, next);
                }
                return;
            }
            if (value is double d)
            {
                float next = EditorGUILayout.FloatField((float)d);
                if (!Mathf.Approximately(next, (float)d) && store != null)
                {
                    store.SetNumber(name, next);
                }
                return;
            }
            if (value is int i)
            {
                int next = EditorGUILayout.IntField(i);
                if (next != i && store != null)
                {
                    store.SetNumber(name, next);
                }
                return;
            }
            if (value is bool b)
            {
                bool next = EditorGUILayout.Toggle(b);
                if (next != b && store != null)
                {
                    store.SetBool(name, next);
                }
                return;
            }
            if (value is string s)
            {
                string next = EditorGUILayout.TextField(s);
                if (next != s && store != null)
                {
                    store.SetString(name, next);
                }
                return;
            }
            EditorGUILayout.SelectableLabel(FormatValue(value), GUILayout.Height(18));
        }

        private static string FormatValue(object value)
        {
            if (value == null) return "(null)";
            return value.ToString();
        }
    }
}
