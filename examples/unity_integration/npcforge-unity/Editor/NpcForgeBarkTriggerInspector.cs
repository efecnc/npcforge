// NpcForgeBarkTriggerInspector.cs
//
// Custom Inspector for NpcForgeBarkTrigger. Renders the default fields,
// then adds a "Fire now" button (Play mode only) and a cooldown bar so
// designers can tell at a glance whether the trigger is hot or still
// cooling down.
//
// Why a custom inspector vs. just UnityEvents? UnityEvents are great for
// wiring up in-scene connections but they don't give you a one-click
// test during play — you'd have to wire up a temporary button, hit it,
// and unwire. This saves that roundtrip.

using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    [CustomEditor(typeof(NpcForgeBarkTrigger))]
    public class NpcForgeBarkTriggerInspector : UnityEditor.Editor
    {
        /// <summary>Quick-pick chips wired to the triggerId field. Values
        /// line up with the Rusted Lantern sample data so the suggestions
        /// aren't meaningless when users first drop the component.</summary>
        private static readonly string[] _triggerSuggestions =
        {
            "greet_patron", "reacts_to_hum", "player_nearby",
            "combat_start", "combat_end", "lost_item",
        };

        public override bool RequiresConstantRepaint()
        {
            // Cooldown bar animates smoothly in Play mode.
            return Application.isPlaying;
        }

        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();

            EditorGUILayout.Space(8);
            EditorGUILayout.HelpBox(
                "Fire bark nodes (<npcId>_Bark_<triggerId>) from any " +
                "gameplay source. Respects cooldownSeconds. Never " +
                "interrupts an in-flight scripted conversation.",
                MessageType.None);

            DrawTriggerSuggestions();
            EditorGUILayout.Space(6);
            DrawPlayModeControls();
        }

        private void DrawTriggerSuggestions()
        {
            EditorGUILayout.LabelField("Common trigger ids", EditorStyles.miniBoldLabel);
            int column = 0;
            EditorGUILayout.BeginHorizontal();
            foreach (string sug in _triggerSuggestions)
            {
                if (GUILayout.Button(sug, EditorStyles.miniButton, GUILayout.MinWidth(70)))
                {
                    var prop = serializedObject.FindProperty("triggerId");
                    if (prop != null)
                    {
                        prop.stringValue = sug;
                        serializedObject.ApplyModifiedProperties();
                    }
                }
                column++;
                if (column % 3 == 0)
                {
                    EditorGUILayout.EndHorizontal();
                    EditorGUILayout.BeginHorizontal();
                }
            }
            EditorGUILayout.EndHorizontal();
        }

        private void DrawPlayModeControls()
        {
            if (!Application.isPlaying)
            {
                EditorGUILayout.HelpBox(
                    "Enter Play mode to fire the trigger manually and " +
                    "visualize the cooldown.",
                    MessageType.Info);
                return;
            }

            var bark = (NpcForgeBarkTrigger)target;

            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("Fire now", GUILayout.Height(26)))
                {
                    bark.TriggerBark();
                }
            }

            DrawCooldownBar(bark);
        }

        private static void DrawCooldownBar(NpcForgeBarkTrigger bark)
        {
            float cooldown = bark.CooldownSeconds;
            if (cooldown <= 0f) return;

            float remaining = Mathf.Max(0f, bark.NextFireTime - Time.time);
            float frac = cooldown > 0f
                ? Mathf.Clamp01(1f - (remaining / cooldown))
                : 1f;
            var rect = GUILayoutUtility.GetRect(0f, 16f, GUILayout.ExpandWidth(true));
            EditorGUI.ProgressBar(rect, frac, remaining > 0f
                ? $"cooling down ({remaining:0.0}s)"
                : "ready");
        }
    }
}
