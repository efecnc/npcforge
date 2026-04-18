// NpcForgeSceneSetup.cs
//
// One-click scene scaffolding. Creates a GameObject hierarchy that's
// ready to run npcforge dialogue in five seconds: an NpcForge controller
// GameObject with DialogueController + StateStore + Startup, a
// DialogueRunner + Canvas DialogueUI pair, a TimeOfDayController hooked
// to the controller, and a sample "Approach Mira" button.
//
// The menu item creates the objects in-place in the active scene; it
// does not save or switch scenes. Users can then mark the scene dirty
// and save with Ctrl/Cmd+S.

using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge.Editor
{
    public static class NpcForgeSceneSetup
    {
        [MenuItem("Tools/npcforge/Create Dialogue Scene Setup", priority = 30)]
        public static void CreateSetup()
        {
#if !NPCFORGE_HAS_YARN
            EditorUtility.DisplayDialog(
                "npcforge",
                "Yarn Spinner for Unity is not installed. Install it " +
                "via Package Manager → Add package from git URL → " +
                "https://github.com/YarnSpinnerTool/YarnSpinner-Unity.git",
                "OK");
            return;
#else
            // Root container so the whole setup is easy to disable / delete.
            var root = new GameObject("NpcForge_Setup");
            Undo.RegisterCreatedObjectUndo(root, "Create npcforge setup");

            // --- Dialogue runtime ---
            var runnerGo = new GameObject("DialogueRunner");
            runnerGo.transform.SetParent(root.transform, false);
            var runner = runnerGo.AddComponent<DialogueRunner>();

            // --- npcforge glue ---
            var forgeGo = new GameObject("NpcForge");
            forgeGo.transform.SetParent(root.transform, false);
            var controller = forgeGo.AddComponent<NpcForgeDialogueController>();
            var store = forgeGo.AddComponent<NpcForgeStateStore>();
            var startup = forgeGo.AddComponent<NpcForgeStartup>();
            var timeOfDay = forgeGo.AddComponent<TimeOfDayController>();
            AssignPrivate(controller, "dialogueRunner", runner);
            AssignPrivate(store, "dialogueRunner", runner);
            AssignPrivate(startup, "controller", controller);
            AssignPrivate(startup, "dialogueRunner", runner);
            AssignPrivate(timeOfDay, "controller", controller);

            // --- Canvas + minimal UI ---
            var canvasGo = new GameObject("NpcForge_Canvas");
            canvasGo.transform.SetParent(root.transform, false);
            var canvas = canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvasGo.AddComponent<CanvasScaler>();
            canvasGo.AddComponent<GraphicRaycaster>();

            // Time-of-day row
            var row = new GameObject("TimeOfDayRow");
            row.transform.SetParent(canvasGo.transform, false);
            var rowRt = row.AddComponent<RectTransform>();
            rowRt.anchorMin = new Vector2(0, 1);
            rowRt.anchorMax = new Vector2(1, 1);
            rowRt.pivot = new Vector2(0.5f, 1f);
            rowRt.sizeDelta = new Vector2(0, 60);
            row.AddComponent<HorizontalLayoutGroup>().spacing = 10;
            CreateTimeButton(row.transform, "Dawn", () => timeOfDay.SetDawn());
            CreateTimeButton(row.transform, "Morning", () => timeOfDay.SetMorning());
            CreateTimeButton(row.transform, "Afternoon", () => timeOfDay.SetAfternoon());
            CreateTimeButton(row.transform, "Dusk", () => timeOfDay.SetDusk());
            CreateTimeButton(row.transform, "Night", () => timeOfDay.SetNight());

            // Approach button
            var approachGo = CreateButton(canvasGo.transform, "Approach Mira");
            var approachRt = approachGo.GetComponent<RectTransform>();
            approachRt.anchorMin = approachRt.anchorMax = new Vector2(0.5f, 0.5f);
            approachRt.pivot = new Vector2(0.5f, 0.5f);
            approachRt.sizeDelta = new Vector2(180, 40);
            var approach = approachGo.AddComponent<NpcApproachButton>();
            AssignPrivate(approach, "controller", controller);
            AssignPrivate(approach, "npcId", "mira_vesser");
            AssignPrivate(approach, "mode", DialogueMode.TimeOfDayGreeting);

            Selection.activeObject = root;
            EditorGUIUtility.PingObject(root);
            Debug.Log("[NpcForge] Scene setup created under 'NpcForge_Setup'. " +
                "Assign a YarnProject to the DialogueRunner to complete wiring.");
#endif
        }

        // -----------------------------------------------------------------

        private static void AssignPrivate(object instance, string fieldName, object value)
        {
            if (instance == null) return;
            var field = instance.GetType().GetField(fieldName,
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic);
            if (field != null)
            {
                field.SetValue(instance, value);
            }
        }

        private static void CreateTimeButton(Transform parent, string label, UnityEngine.Events.UnityAction onClick)
        {
            var go = CreateButton(parent, label);
            var btn = go.GetComponent<Button>();
            btn.onClick.AddListener(onClick);
        }

        private static GameObject CreateButton(Transform parent, string label)
        {
            var go = new GameObject(label);
            go.transform.SetParent(parent, false);
            var img = go.AddComponent<Image>();
            img.color = new Color(0.15f, 0.2f, 0.25f, 0.85f);
            var btn = go.AddComponent<Button>();
            btn.targetGraphic = img;

            var txtGo = new GameObject("Text");
            txtGo.transform.SetParent(go.transform, false);
            var txt = txtGo.AddComponent<Text>();
            txt.text = label;
            txt.alignment = TextAnchor.MiddleCenter;
            txt.color = Color.white;
            txt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            var txtRt = txt.GetComponent<RectTransform>();
            txtRt.anchorMin = Vector2.zero;
            txtRt.anchorMax = Vector2.one;
            txtRt.offsetMin = txtRt.offsetMax = Vector2.zero;
            return go;
        }
    }
}
