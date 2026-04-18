// NpcForgeStateStoreInspector.cs
//
// Custom Inspector for NpcForgeStateStore. In Edit mode it shows the
// default inspector plus a help box explaining the component. In Play
// mode it adds a live snapshot table of every variable the store has
// observed, plus typed quick-set fields so designers can poke values
// while the scene is running without writing code.
//
// The underlying truth lives in Yarn's VariableStorage; this inspector
// is a thin surface on top of the store's Snapshot dictionary plus its
// typed setters.

using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    [CustomEditor(typeof(NpcForgeStateStore))]
    public class NpcForgeStateStoreInspector : UnityEditor.Editor
    {
        private string _setName = "$time_of_day";
        private string _setStringValue = "dusk";
        private float _setNumberValue = 0f;
        private bool _setBoolValue = false;
        private int _quickType;
        private static readonly string[] _quickTypeLabels = { "String", "Number", "Bool" };

        public override bool RequiresConstantRepaint()
        {
            // 5 Hz-ish repaint in Play mode so the snapshot table stays
            // fresh while variables change underneath us.
            return Application.isPlaying;
        }

        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();

            EditorGUILayout.Space(8);
            EditorGUILayout.HelpBox(
                "Typed wrapper around Yarn's VariableStorage. Fires " +
                "OnVariableChanged(name, value) on every write; keeps a " +
                "snapshot of observed values so the Inspector can show " +
                "something even before Yarn has run a node.",
                MessageType.None);

            if (!Application.isPlaying)
            {
                EditorGUILayout.Space(4);
                EditorGUILayout.HelpBox(
                    "Enter Play mode to see live variable values.",
                    MessageType.Info);
                return;
            }

            var store = (NpcForgeStateStore)target;
            DrawSnapshotTable(store);
            EditorGUILayout.Space(8);
            DrawQuickSet(store);
        }

        private void DrawSnapshotTable(NpcForgeStateStore store)
        {
            EditorGUILayout.LabelField("Live snapshot", EditorStyles.boldLabel);
            var snap = store.Snapshot;
            if (snap == null || snap.Count == 0)
            {
                EditorGUILayout.LabelField("(empty — no variable reads/writes yet)",
                    EditorStyles.miniLabel);
                return;
            }

            using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    EditorGUILayout.LabelField("Variable", EditorStyles.miniBoldLabel,
                        GUILayout.MinWidth(140));
                    EditorGUILayout.LabelField("Type", EditorStyles.miniBoldLabel,
                        GUILayout.Width(60));
                    EditorGUILayout.LabelField("Value", EditorStyles.miniBoldLabel);
                }

                // Stable order for a calmer display — sorting by key every
                // frame is cheap because the snapshot is always tiny
                // (tens of variables in practice).
                var keys = new List<string>(snap.Keys);
                keys.Sort();
                foreach (string k in keys)
                {
                    object v = snap[k];
                    using (new EditorGUILayout.HorizontalScope())
                    {
                        EditorGUILayout.LabelField(k, GUILayout.MinWidth(140));
                        EditorGUILayout.LabelField(
                            v == null ? "—" : v.GetType().Name,
                            GUILayout.Width(60));
                        EditorGUILayout.SelectableLabel(
                            v == null ? "null" : v.ToString(),
                            EditorStyles.textField,
                            GUILayout.Height(EditorGUIUtility.singleLineHeight));
                    }
                }
            }
        }

        private void DrawQuickSet(NpcForgeStateStore store)
        {
            EditorGUILayout.LabelField("Quick-set variable", EditorStyles.boldLabel);
            _setName = EditorGUILayout.TextField("Name (with $ prefix)", _setName);
            _quickType = EditorGUILayout.Popup("Type", _quickType, _quickTypeLabels);

            switch (_quickType)
            {
                case 0:
                    _setStringValue = EditorGUILayout.TextField("Value", _setStringValue);
                    if (GUILayout.Button("Set"))
                        store.SetString(_setName, _setStringValue);
                    break;
                case 1:
                    _setNumberValue = EditorGUILayout.FloatField("Value", _setNumberValue);
                    if (GUILayout.Button("Set"))
                        store.SetNumber(_setName, _setNumberValue);
                    break;
                case 2:
                    _setBoolValue = EditorGUILayout.Toggle("Value", _setBoolValue);
                    if (GUILayout.Button("Set"))
                        store.SetBool(_setName, _setBoolValue);
                    break;
            }
        }
    }
}
