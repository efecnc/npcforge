// NpcForgeStartup.cs
//
// Seeds initial Yarn variable values at scene load so scenes that jump
// directly into an NPC node (instead of running the Start node first)
// still have the expected state.
//
// Yarn's <<declare>> lines in world.yarn only fire when their node runs.
// If your scene plays Mira's greeting without ever running Start, those
// declares haven't been seen yet and the variable lookups fail. This
// script seeds the values directly at scene load or runs the Start node
// once, depending on the Inspector toggle.

using UnityEngine;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge
{
    public class NpcForgeStartup : MonoBehaviour
    {
        [SerializeField] private NpcForgeDialogueController controller;

#if NPCFORGE_HAS_YARN
        [SerializeField] private DialogueRunner dialogueRunner;
#endif

        [Tooltip("If true, set the default variables directly at Start(). " +
                 "If false, run the Start node which fires its <<declare>> lines.")]
        [SerializeField] private bool seedDirectly = true;

        [Tooltip("Default value for $time_of_day. Must match variables.yaml.")]
        [SerializeField] private string defaultTimeOfDay = "morning";

        [Tooltip("Default value for $disposition_<npc>. Neutral = 50.")]
        [SerializeField] private float defaultDisposition = 50f;

        private void Start()
        {
            if (seedDirectly)
            {
                SeedDefaults();
            }
            else if (controller != null)
            {
                controller.PlayStart();
            }
        }

        /// <summary>Direct seed path — bypasses dialogue UI entirely. Values
        /// MUST match the defaults in variables.yaml to keep generated
        /// content consistent.</summary>
        private void SeedDefaults()
        {
#if NPCFORGE_HAS_YARN
            if (dialogueRunner == null) return;
            var storage = dialogueRunner.VariableStorage;
            if (!storage.TryGetValue("$time_of_day", out string _))
            {
                storage.SetValue("$time_of_day", defaultTimeOfDay);
            }
#endif
        }
    }
}
