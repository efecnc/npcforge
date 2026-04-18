// NpcForgeDialogueController.cs
//
// Orchestrates dialogue playback for npcforge-generated Yarn files in Unity.
// Owns the Yarn `DialogueRunner` and exposes helper methods to:
//   - Set the `$time_of_day` project variable (for enum-keyed greetings).
//   - Play a specific node by convention (walk-up, time-of-day greeting,
//     repeat greeting) without the caller typing raw node names.
//
// Wire one of these into a Unity scene, assign your DialogueRunner in the
// Inspector, and call the public methods from UI buttons or game code.

using UnityEngine;
using Yarn.Unity;

namespace NpcForge
{
    public class NpcForgeDialogueController : MonoBehaviour
    {
        [Tooltip("The Yarn Spinner DialogueRunner that owns the compiled project.")]
        [SerializeField] private DialogueRunner dialogueRunner;

        // ---------------------------------------------------------------
        // State setters
        // ---------------------------------------------------------------

        /// <summary>Set the Yarn variable <c>$time_of_day</c>. Values should
        /// match the enum declared in <c>variables.yaml</c>
        /// (dawn / morning / afternoon / dusk / night).</summary>
        public void SetTimeOfDay(string value)
        {
            if (dialogueRunner == null)
            {
                Debug.LogError("[NpcForge] DialogueRunner is not assigned.");
                return;
            }
            dialogueRunner.VariableStorage.SetValue("$time_of_day", value);
            Debug.Log($"[NpcForge] time_of_day set to '{value}'.");
        }

        /// <summary>Bump Mira's disposition by <paramref name="delta"/>. Clamps
        /// to [0, 100]. Extend this as more NPCs get disposition tracking.</summary>
        public void AdjustMiraDisposition(float delta)
        {
            if (dialogueRunner.VariableStorage.TryGetValue("$disposition_mira", out float current))
            {
                float next = Mathf.Clamp(current + delta, 0f, 100f);
                dialogueRunner.VariableStorage.SetValue("$disposition_mira", next);
            }
        }

        // ---------------------------------------------------------------
        // Dialogue entry points (one per generator output type)
        // ---------------------------------------------------------------

        /// <summary>Play an NPC's <c>$time_of_day</c>-keyed greeting. Node
        /// convention: <c>{npcId}_Greet_time_of_day</c>.</summary>
        public void PlayTimeOfDayGreeting(string npcId)
        {
            StartNode($"{npcId}_Greet_time_of_day");
        }

        /// <summary>Play an NPC's visit-count-gated repeat greeting. Node
        /// convention: <c>{npcId}_RepeatGreet</c>. Yarn's built-in
        /// <c>visited_count()</c> tracks the visit index automatically —
        /// no manual variable increment required.</summary>
        public void PlayRepeatGreeting(string npcId)
        {
            StartNode($"{npcId}_RepeatGreet");
        }

        /// <summary>Play the walk-up dialogue node for an NPC. Node
        /// convention: the NPC's id (e.g. <c>mira_vesser</c>).</summary>
        public void PlayWalkUp(string npcId)
        {
            StartNode(npcId);
        }

        /// <summary>Play the world-entry Start node. Useful at scene load to
        /// run the <c>&lt;&lt;declare&gt;&gt;</c> statements.</summary>
        public void PlayStart()
        {
            StartNode("Start");
        }

        // ---------------------------------------------------------------
        // Internals
        // ---------------------------------------------------------------

        private void StartNode(string node)
        {
            if (dialogueRunner == null)
            {
                Debug.LogError("[NpcForge] DialogueRunner is not assigned.");
                return;
            }
            if (dialogueRunner.IsDialogueRunning)
            {
                dialogueRunner.Stop();
            }
            dialogueRunner.StartDialogue(node);
        }
    }
}
