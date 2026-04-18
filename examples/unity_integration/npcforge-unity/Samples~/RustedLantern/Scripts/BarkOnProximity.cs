// BarkOnProximity.cs
//
// Sample script — distance-based trigger for NpcForgeBarkTrigger.
// Drop onto an NPC GameObject, point ``player`` at the player Transform,
// tune ``triggerDistance``, and the bark fires once the player crosses
// the threshold. Cooldown is enforced by the bark trigger itself.
//
// This is illustrative wiring rather than the only way to do it — for
// real games you'd probably prefer physics triggers (OnTriggerEnter)
// so the check is event-driven instead of per-frame.

using UnityEngine;

namespace Altai.NpcForge.Samples.RustedLantern
{
    [RequireComponent(typeof(NpcForgeBarkTrigger))]
    public class BarkOnProximity : MonoBehaviour
    {
        [Tooltip("The player (or whoever's proximity matters here).")]
        [SerializeField] private Transform player;

        [Tooltip("World-units distance at which the bark fires.")]
        [SerializeField, Min(0.1f)] private float triggerDistance = 3f;

        private NpcForgeBarkTrigger _bark;
        private bool _inside;

        private void Awake()
        {
            _bark = GetComponent<NpcForgeBarkTrigger>();
        }

        private void Update()
        {
            if (player == null || _bark == null) return;

            float sqr = (player.position - transform.position).sqrMagnitude;
            bool nowInside = sqr < triggerDistance * triggerDistance;

            // Rising edge only — we don't want to spam the bark every
            // frame while the player hangs out inside the radius.
            if (nowInside && !_inside)
            {
                _bark.TriggerBark();
            }
            _inside = nowInside;
        }

        private void OnDrawGizmosSelected()
        {
            Gizmos.color = new Color(0.95f, 0.6f, 0.2f, 0.55f);
            Gizmos.DrawWireSphere(transform.position, triggerDistance);
        }
    }
}
