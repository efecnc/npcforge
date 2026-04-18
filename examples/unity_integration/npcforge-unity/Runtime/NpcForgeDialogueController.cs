// NpcForgeDialogueController.cs
//
// Orchestrates dialogue playback for npcforge-generated Yarn files.
// Owns the Yarn DialogueRunner and exposes helper methods to:
//   - Set the $time_of_day project variable (for enum-keyed greetings).
//   - Play a specific node by convention (walk-up, time-of-day greeting,
//     repeat greeting) without the caller typing raw node names.
//
// Node conventions (mirror npcforge's file naming):
//   - <npc>                       walk-up tree with intent options
//   - <npc>_Greet_time_of_day     enum-keyed greeting chain
//   - <npc>_RepeatGreet           visit-counter greeting
//
// Wire one of these into a scene, assign a DialogueRunner in the
// Inspector, and call the public methods from UI buttons or game code.

using UnityEngine;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge
{
    public class NpcForgeDialogueController : MonoBehaviour
    {
#if NPCFORGE_HAS_YARN
        [Tooltip("The Yarn Spinner DialogueRunner that owns the compiled project.")]
        [SerializeField] private DialogueRunner dialogueRunner;
#endif

        // ---------------------------------------------------------------
        // State setters
        // ---------------------------------------------------------------

        /// <summary>Set the Yarn variable $time_of_day. Values should match
        /// the enum declared in variables.yaml (dawn / morning / afternoon /
        /// dusk / night by default in the Rusted Lantern demo).</summary>
        public void SetTimeOfDay(string value)
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner == null)
            {
                Debug.LogError("[NpcForge] DialogueRunner is not assigned.");
                return;
            }
            dialogueRunner.VariableStorage.SetValue("$time_of_day", value);
            Debug.Log($"[NpcForge] time_of_day set to '{value}'.");
#else
            Debug.LogWarning("[NpcForge] Yarn Spinner is not installed. Install the " +
                "YarnSpinner-Unity package via Package Manager.");
#endif
        }

        /// <summary>Bump an NPC's disposition by delta. Clamps to [0, 100].
        /// The Yarn variable name convention is $disposition_<npcId>.</summary>
        public void AdjustDisposition(string npcId, float delta)
        {
#if NPCFORGE_HAS_YARN
            string key = $"$disposition_{npcId}";
            if (dialogueRunner.VariableStorage.TryGetValue(key, out float current))
            {
                float next = Mathf.Clamp(current + delta, 0f, 100f);
                dialogueRunner.VariableStorage.SetValue(key, next);
            }
#endif
        }

        // ---------------------------------------------------------------
        // Dialogue entry points — one per generator output type
        // ---------------------------------------------------------------

        /// <summary>Play an NPC's $time_of_day-keyed greeting.
        /// Node: <c>{npcId}_Greet_time_of_day</c>.</summary>
        public void PlayTimeOfDayGreeting(string npcId)
        {
            StartNode($"{npcId}_Greet_time_of_day");
        }

        /// <summary>Play an NPC's visit-count-gated repeat greeting.
        /// Node: <c>{npcId}_RepeatGreet</c>. Yarn's built-in visited_count()
        /// tracks the visit index automatically — no manual increment.</summary>
        public void PlayRepeatGreeting(string npcId)
        {
            StartNode($"{npcId}_RepeatGreet");
        }

        /// <summary>Play the walk-up dialogue node for an NPC.
        /// Node: the NPC id itself (e.g. <c>mira_vesser</c>).</summary>
        public void PlayWalkUp(string npcId)
        {
            StartNode(npcId);
        }

        /// <summary>Play the world-entry Start node. Useful once at scene
        /// load to run the &lt;&lt;declare&gt;&gt; statements npcforge emits
        /// at the top of world.yarn.</summary>
        public void PlayStart()
        {
            StartNode("Start");
        }

        // ---------------------------------------------------------------
        // Internals
        // ---------------------------------------------------------------

        private void StartNode(string node)
        {
#if NPCFORGE_HAS_YARN
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
#endif
        }
    }
}
