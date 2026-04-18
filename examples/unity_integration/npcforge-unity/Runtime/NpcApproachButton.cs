// NpcApproachButton.cs
//
// Attach to a Unity Button. Pick an NPC id and a DialogueMode in the
// Inspector; the button plays the right generated Yarn node. The mode
// maps one-to-one to npcforge's generator outputs:
//
//   TimeOfDayGreeting → <npc>_Greet_time_of_day   (gen greetings)
//   RepeatGreeting    → <npc>_RepeatGreet         (gen repeat-greeting)
//   WalkUp            → <npc>                     (build --mode walk_up)

using UnityEngine;
using UnityEngine.UI;

namespace Altai.NpcForge
{
    public enum DialogueMode
    {
        TimeOfDayGreeting,
        RepeatGreeting,
        WalkUp,
    }

    [RequireComponent(typeof(Button))]
    public class NpcApproachButton : MonoBehaviour
    {
        [SerializeField] private NpcForgeDialogueController controller;

        [Tooltip("NPC id exactly as declared in characters.yaml (e.g. 'mira_vesser').")]
        [SerializeField] private string npcId;

        [SerializeField] private DialogueMode mode = DialogueMode.TimeOfDayGreeting;

        private void Awake()
        {
            GetComponent<Button>().onClick.AddListener(Approach);
        }

        public void Approach()
        {
            if (controller == null || string.IsNullOrEmpty(npcId))
            {
                Debug.LogError("[NpcForge] NpcApproachButton is missing controller or npcId.");
                return;
            }

            switch (mode)
            {
                case DialogueMode.TimeOfDayGreeting:
                    controller.PlayTimeOfDayGreeting(npcId);
                    break;
                case DialogueMode.RepeatGreeting:
                    controller.PlayRepeatGreeting(npcId);
                    break;
                case DialogueMode.WalkUp:
                    controller.PlayWalkUp(npcId);
                    break;
            }
        }
    }
}
