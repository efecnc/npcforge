// NpcForgeBarkTrigger.cs
//
// Invoke a generated bark library from any gameplay event: a collision,
// an animation event, a UnityEvent wired from another script, a timer,
// whatever. The bark node is addressed by {npcId}_Bark_{triggerId} to
// match npcforge's file-naming convention.
//
// Three input paths on one component:
//   - Unity Event                  call TriggerBark() from UI, animation events
//   - OnTriggerEnter2D / 3D        collision-based firing (optional)
//   - Explicit FireFor(triggerId)  game code picks the trigger at runtime
//
// Cooldown seconds prevents the same bark firing on every frame of a
// collision event. Set to 0 for no cooldown.

using UnityEngine;
using UnityEngine.Events;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge
{
    public class NpcForgeBarkTrigger : MonoBehaviour
    {
#if NPCFORGE_HAS_YARN
        [SerializeField] private DialogueRunner dialogueRunner;
#endif

        [Tooltip("NPC id exactly as declared in characters.yaml.")]
        [SerializeField] private string npcId;

        [Tooltip("Trigger id — e.g. 'greet_patron', 'reacts_to_hum', 'combat_start'.")]
        [SerializeField] private string triggerId;

        [Tooltip("Seconds of cooldown between successive fires. 0 = no cooldown.")]
        [SerializeField, Min(0f)] private float cooldownSeconds = 0.5f;

        [Tooltip("Invoked after the bark node starts. Useful for chaining audio or SFX.")]
        public UnityEvent onBarkFired;

        private float _nextFireTime;

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        /// <summary>Fire the component's configured trigger.</summary>
        public void TriggerBark()
        {
            FireFor(triggerId);
        }

        /// <summary>Fire a specific trigger id by name. Respects cooldown.</summary>
        public void FireFor(string trigger)
        {
            if (string.IsNullOrEmpty(npcId) || string.IsNullOrEmpty(trigger))
            {
                Debug.LogWarning("[NpcForgeBarkTrigger] Missing npcId or triggerId.");
                return;
            }
            if (Time.time < _nextFireTime) return;
            _nextFireTime = Time.time + cooldownSeconds;

#if NPCFORGE_HAS_YARN
            if (dialogueRunner == null)
            {
                Debug.LogWarning("[NpcForgeBarkTrigger] DialogueRunner not assigned.");
                return;
            }
            string node = $"{npcId}_Bark_{trigger}";
            if (dialogueRunner.IsDialogueRunning)
            {
                // Don't interrupt an in-progress scripted conversation with a
                // bark. The bark gets dropped rather than queued — barks are
                // ambient and stale barks help no-one.
                return;
            }
            dialogueRunner.StartDialogue(node);
            onBarkFired?.Invoke();
#endif
        }

        // ---------------------------------------------------------------
        // Collision-based firing (opt-in — both 2D and 3D flavours)
        // ---------------------------------------------------------------

        [Header("Collision (optional)")]
        [Tooltip("Fire when any other collider enters this one. Requires a Collider with isTrigger = true.")]
        [SerializeField] private bool fireOnTriggerEnter = false;

        [Tooltip("Only fire when the entering collider has one of these tags. Leave empty to fire for anything.")]
        [SerializeField] private string[] triggerTags = { "Player" };

        private bool AcceptsTag(string tag)
        {
            if (triggerTags == null || triggerTags.Length == 0) return true;
            foreach (string t in triggerTags)
            {
                if (t == tag) return true;
            }
            return false;
        }

        private void OnTriggerEnter(Collider other)
        {
            if (!fireOnTriggerEnter) return;
            if (AcceptsTag(other.tag)) TriggerBark();
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (!fireOnTriggerEnter) return;
            if (AcceptsTag(other.tag)) TriggerBark();
        }
    }
}
