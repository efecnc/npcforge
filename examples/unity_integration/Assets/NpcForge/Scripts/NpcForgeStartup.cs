// NpcForgeStartup.cs
//
// Seeds initial Yarn variable values at scene load so scenes that jump
// directly into an NPC node (instead of running the Start node first)
// still have the expected state.
//
// Yarn's `<<declare>>` lines in world.yarn only fire when their node runs.
// If your scene plays Mira's greeting without ever running Start, those
// declares haven't been seen yet and the variable lookups fail. This
// script calls Start() on the dialogue runner at scene load to run the
// declares without actually showing the Start node's dialogue UI — or,
// optionally, seeds the values directly.
//
// Pick one of the two strategies below by toggling the Inspector flag.

using UnityEngine;
using Yarn.Unity;

namespace NpcForge
{
    public class NpcForgeStartup : MonoBehaviour
    {
        [SerializeField] private NpcForgeDialogueController controller;
        [SerializeField] private DialogueRunner dialogueRunner;

        [Tooltip("If true, set the default variables directly at Start(). " +
                 "If false, run the Start node which fires its <<declare>> lines.")]
        [SerializeField] private bool seedDirectly = true;

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
            if (dialogueRunner == null) return;
            var storage = dialogueRunner.VariableStorage;
            if (!storage.TryGetValue("$time_of_day", out string _))
            {
                storage.SetValue("$time_of_day", "morning");
            }
            if (!storage.TryGetValue("$disposition_mira", out float _))
            {
                storage.SetValue("$disposition_mira", 50f);
            }
        }
    }
}
