// TimeOfDayController.cs
//
// Plain UI glue: wire one button per enum value to the matching setter.
// Each setter calls NpcForgeDialogueController.SetTimeOfDay with the
// string that matches the enum declared in variables.yaml.
//
// The enum values MUST match variables.yaml exactly. If you added or
// removed values there (or declared a different enum variable), edit
// this script to match. The generator emits Yarn that references these
// exact strings.

using UnityEngine;

namespace NpcForge
{
    public class TimeOfDayController : MonoBehaviour
    {
        [SerializeField] private NpcForgeDialogueController controller;

        public void SetDawn()      { controller.SetTimeOfDay("dawn"); }
        public void SetMorning()   { controller.SetTimeOfDay("morning"); }
        public void SetAfternoon() { controller.SetTimeOfDay("afternoon"); }
        public void SetDusk()      { controller.SetTimeOfDay("dusk"); }
        public void SetNight()     { controller.SetTimeOfDay("night"); }
    }
}
