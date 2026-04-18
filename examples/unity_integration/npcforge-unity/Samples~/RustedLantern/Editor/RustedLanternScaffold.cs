// RustedLanternScaffold.cs
//
// Sample entry point that composes the same Scene-Setup scaffolding
// users get from Tools → npcforge → Create Dialogue Scene Setup, but
// branded for the Rusted Lantern tavern demo. Lives inside the sample
// so it only loads once the user explicitly imports it.
//
// We deliberately call through to the core NpcForgeSceneSetup menu so
// the sample stays a thin veneer rather than a second scaffolder we
// have to keep in sync.

using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Samples.RustedLantern
{
    public static class RustedLanternScaffold
    {
        [MenuItem("Tools/npcforge/Samples/Scaffold Rusted Lantern Scene", priority = 200)]
        public static void Scaffold()
        {
            // Delegating to the main package's scene-setup menu so the
            // sample's scaffolding stays in sync with the authored one.
            // If the user hasn't installed Yarn Spinner yet the delegate
            // surfaces its own dialog.
            EditorApplication.ExecuteMenuItem("Tools/npcforge/Create Dialogue Scene Setup");

            Debug.Log("[NpcForge Sample] Rusted Lantern scaffolded. " +
                "Assign a YarnProject to the DialogueRunner and press Play.");
            Debug.Log("[NpcForge Sample] If no Yarn files exist yet, run " +
                "the main panel's 'Build All' + 'Sync now' first.");
        }
    }
}
