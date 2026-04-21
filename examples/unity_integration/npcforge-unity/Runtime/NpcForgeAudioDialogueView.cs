// NpcForgeAudioDialogueView.cs
//
// A Yarn Spinner DialogueView that plays an AudioClip for every line
// Yarn delivers, looking the clip up in an NpcForgeAudioMap keyed by
// the npcforge line_id.
//
// Wiring:
//   1. Drop onto the same GameObject as your DialogueRunner.
//   2. Assign a NpcForgeAudioMap.
//   3. Assign (or let it auto-create) an AudioSource.
//   4. Add this component to the DialogueRunner's "Dialogue Views" list.
//
// Line-id extraction: Yarn's LocalizedLine.TextID looks like
// ``line:mira_vesser_abc123def4``; npcforge writes its line_ids without
// the ``line:`` prefix, so we strip it before the map lookup.
//
// Finish semantics: we call the Yarn-provided "line finished" callback
// exactly once — either when the clip finishes or when Time.time hits
// the estimated duration (whichever is shorter), or immediately if no
// clip is mapped. The next view in Yarn's pipeline (typically a LineView
// for the on-screen text) still runs in parallel.

using System;
using UnityEngine;

#if NPCFORGE_HAS_YARN
using Yarn.Unity;
#endif

namespace Altai.NpcForge
{
#if NPCFORGE_HAS_YARN
    [RequireComponent(typeof(AudioSource))]
    public class NpcForgeAudioDialogueView : DialogueViewBase
    {
        [Tooltip("The npcforge audio map that holds line_id → AudioClip.")]
        [SerializeField] private NpcForgeAudioMap audioMap;

        [Tooltip("AudioSource that plays dialogue clips. If empty, " +
                 "the one on this GameObject is used.")]
        [SerializeField] private AudioSource audioSource;

        [Tooltip("If true, missing clips log a warning. Turn off once " +
                 "your coverage is complete to quiet the console.")]
        [SerializeField] private bool warnOnMissingClip = true;

        [Tooltip("If true, the view calls the Yarn line-finished callback " +
                 "when the clip finishes playing. If false, control returns " +
                 "immediately and Yarn moves on (useful when another view " +
                 "owns pacing).")]
        [SerializeField] private bool waitForClipToFinish = true;

        private Action _pendingFinish;
        private AudioClip _currentClip;
        private float _clipStartTime;

        private void Awake()
        {
            if (audioSource == null) audioSource = GetComponent<AudioSource>();
        }

        public override void RunLine(LocalizedLine dialogueLine, Action onDialogueLineFinished)
        {
            string lineId = StripPrefix(dialogueLine?.TextID);
            var entry = audioMap != null ? audioMap.GetEntry(lineId) : null;

            if (entry == null || entry.clip == null)
            {
                if (warnOnMissingClip && !string.IsNullOrEmpty(lineId))
                {
                    Debug.LogWarning($"[NpcForgeAudio] No clip for line_id {lineId}");
                }
                onDialogueLineFinished?.Invoke();
                return;
            }

            _currentClip = entry.clip;
            _clipStartTime = Time.time;
            audioSource.volume = entry.volume;
            audioSource.clip = entry.clip;
            audioSource.Play();

            if (waitForClipToFinish)
            {
                _pendingFinish = onDialogueLineFinished;
            }
            else
            {
                onDialogueLineFinished?.Invoke();
            }
        }

        public override void InterruptLine(LocalizedLine dialogueLine, Action onDialogueLineFinished)
        {
            // An interrupt asks us to stop playback early and confirm when we're done.
            if (audioSource != null && audioSource.isPlaying) audioSource.Stop();
            _pendingFinish = null;
            _currentClip = null;
            onDialogueLineFinished?.Invoke();
        }

        public override void DismissLine(Action onDismissalComplete)
        {
            // Between lines — no audio wind-down needed since we stopped in Interrupt.
            onDismissalComplete?.Invoke();
        }

        public override void UserRequestedViewAdvancement()
        {
            // The player clicked / hit space — if we're waiting on a clip,
            // short-circuit and call finished now so the dialogue doesn't hang.
            if (_pendingFinish != null)
            {
                if (audioSource != null && audioSource.isPlaying) audioSource.Stop();
                var cb = _pendingFinish;
                _pendingFinish = null;
                _currentClip = null;
                cb.Invoke();
            }
        }

        private void Update()
        {
            if (_pendingFinish == null || _currentClip == null) return;
            if (audioSource == null) return;

            // Fire the finish callback when the clip has finished playing.
            // AudioSource.isPlaying flips false either naturally at end-of-
            // clip or when Stop() is called. We guard with the clip's own
            // length + a 0.05s buffer in case AudioSource's bookkeeping
            // is slow on one frame.
            bool naturalEnd = !audioSource.isPlaying;
            bool timeoutReached = Time.time - _clipStartTime > _currentClip.length + 0.05f;
            if (naturalEnd || timeoutReached)
            {
                var cb = _pendingFinish;
                _pendingFinish = null;
                _currentClip = null;
                cb.Invoke();
            }
        }

        /// <summary>Strip Yarn's ``line:`` prefix from a TextID to get the
        /// raw npcforge line_id. Public + static so tests and callers can
        /// reuse it.</summary>
        public static string StripPrefix(string textId)
        {
            if (string.IsNullOrEmpty(textId)) return string.Empty;
            const string prefix = "line:";
            return textId.StartsWith(prefix, StringComparison.Ordinal)
                ? textId.Substring(prefix.Length)
                : textId;
        }
    }
#else
    // No Yarn Spinner installed — keep a stub component so scenes that
    // reference the type by name still deserialize; it just does nothing.
    public class NpcForgeAudioDialogueView : MonoBehaviour
    {
        public static string StripPrefix(string textId)
        {
            if (string.IsNullOrEmpty(textId)) return string.Empty;
            const string prefix = "line:";
            return textId.StartsWith(prefix, System.StringComparison.Ordinal)
                ? textId.Substring(prefix.Length)
                : textId;
        }
    }
#endif
}
