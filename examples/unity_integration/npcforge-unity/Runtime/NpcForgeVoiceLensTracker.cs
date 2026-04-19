// NpcForgeVoiceLensTracker.cs
//
// Runtime companion to Python's v0.14.0 voice lenses. Tracks WHICH
// lenses are currently active for an NPC (tipsy, with_inspector_
// present, grindholt_formal) and composes a prompt-ready summary the
// improv client can splice into its system prompt.
//
// Lens definitions are authored in characters.yaml on the Python
// side; the runtime doesn't re-author, it just tracks activation.
// Projects that want to author lenses in Unity can serialise
// NpcForgeVoiceLensSpec into the inspector; either way the prompt
// output shape is the same.
//
// Activation model:
// - ActivateLens(id)       — marks the lens on
// - DeactivateLens(id)     — marks it off
// - SetActiveLenses(ids)   — replaces the set wholesale
// - IsActive(id)           — query
//
// Cultural lenses typically stay on for the character's whole life;
// state lenses turn on/off during gameplay (tipsy → sober); audience
// lenses flip based on scene occupancy. All three share the same API.

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Events;

namespace Altai.NpcForge
{
    [Serializable]
    public class NpcForgeVoiceLensSpec
    {
        public string id;
        public string label;
        /// <summary>"state" | "audience" | "cultural" — matches the Python Literal.</summary>
        public string kind = "state";
        public string cadence_shift;
        public List<string> extra_forbidden_words = new List<string>();
        public List<string> extra_accent_markers = new List<string>();
        public string description = "";
    }

    public class NpcForgeVoiceLensTracker : MonoBehaviour
    {
        [Tooltip("Lens definitions authored for this NPC. Usually loaded " +
                 "from characters.yaml via the npcforge export; can also " +
                 "be authored directly in the Inspector.")]
        [SerializeField] private List<NpcForgeVoiceLensSpec> lenses
            = new List<NpcForgeVoiceLensSpec>();

        [Tooltip("Lens ids that start active at scene load. Cultural " +
                 "lenses typically go here.")]
        [SerializeField] private List<string> startActive = new List<string>();

        [Header("Events")]
        public UnityEvent<string> onLensActivated = new UnityEvent<string>();
        public UnityEvent<string> onLensDeactivated = new UnityEvent<string>();

        private readonly HashSet<string> _active = new HashSet<string>();

        public IReadOnlyList<NpcForgeVoiceLensSpec> Lenses => lenses;

        private void Awake()
        {
            foreach (var id in startActive)
            {
                if (!string.IsNullOrEmpty(id)) _active.Add(id);
            }
        }

        // ---------------------------------------------------------------
        // Public API
        // ---------------------------------------------------------------

        public bool IsActive(string lensId)
            => !string.IsNullOrEmpty(lensId) && _active.Contains(lensId);

        /// <summary>Turn a lens on. Silent no-op if already active, or if
        /// the lens id isn't declared for this NPC.</summary>
        public void ActivateLens(string lensId)
        {
            if (!HasLens(lensId)) return;
            if (_active.Add(lensId)) onLensActivated?.Invoke(lensId);
        }

        /// <summary>Turn a lens off. Silent no-op if already inactive.</summary>
        public void DeactivateLens(string lensId)
        {
            if (_active.Remove(lensId)) onLensDeactivated?.Invoke(lensId);
        }

        public void ToggleLens(string lensId)
        {
            if (IsActive(lensId)) DeactivateLens(lensId);
            else ActivateLens(lensId);
        }

        /// <summary>Replace the active set wholesale. Useful when a scene
        /// transitions and every audience lens flips at once.</summary>
        public void SetActiveLenses(IEnumerable<string> ids)
        {
            var target = new HashSet<string>();
            if (ids != null)
            {
                foreach (var id in ids)
                    if (HasLens(id)) target.Add(id);
            }
            // Fire deactivations for lenses leaving the set.
            var leaving = new List<string>();
            foreach (var existing in _active)
                if (!target.Contains(existing)) leaving.Add(existing);
            foreach (var id in leaving)
            {
                _active.Remove(id);
                onLensDeactivated?.Invoke(id);
            }
            // Fire activations for lenses joining.
            foreach (var id in target)
            {
                if (_active.Add(id)) onLensActivated?.Invoke(id);
            }
        }

        /// <summary>Return the subset of declared lenses whose ids are
        /// currently active, in declaration order.</summary>
        public List<NpcForgeVoiceLensSpec> ActiveLenses()
        {
            var result = new List<NpcForgeVoiceLensSpec>();
            foreach (var l in lenses)
                if (_active.Contains(l.id)) result.Add(l);
            return result;
        }

        /// <summary>Compose the prompt block Python's _render_voice_lenses
        /// produces. Matches shape so the improv client can splice this
        /// into its system prompt alongside the player-profile block.</summary>
        public string SummarizeActive()
        {
            var active = ActiveLenses();
            if (active.Count == 0) return string.Empty;

            var sb = new StringBuilder();
            sb.AppendLine(
                "Active voice lenses (situational modifiers; apply every "
                + "cadence_shift cumulatively — they compose with your base voice "
                + "and with each other, they do not replace anything):");
            foreach (var l in active)
            {
                sb.AppendLine($"- {l.kind}: {l.label} ({l.id})");
                sb.AppendLine($"    Cadence shift: {(l.cadence_shift ?? "").Trim()}");
                if (!string.IsNullOrWhiteSpace(l.description))
                    sb.AppendLine($"    Note: {l.description.Trim()}");
            }

            // Dedup extras across active lenses — same behaviour as Python.
            var extraForbidden = new List<string>();
            var seenForbidden = new HashSet<string>();
            var extraAccent = new List<string>();
            var seenAccent = new HashSet<string>();
            foreach (var l in active)
            {
                if (l.extra_forbidden_words != null)
                    foreach (var w in l.extra_forbidden_words)
                        if (seenForbidden.Add(w)) extraForbidden.Add(w);
                if (l.extra_accent_markers != null)
                    foreach (var m in l.extra_accent_markers)
                        if (seenAccent.Add(m)) extraAccent.Add(m);
            }
            if (extraForbidden.Count > 0)
            {
                var quoted = new List<string>(extraForbidden.Count);
                foreach (var w in extraForbidden) quoted.Add($"\"{w}\"");
                sb.AppendLine(
                    "    Extra forbidden words (from active lenses): "
                    + string.Join(", ", quoted));
            }
            if (extraAccent.Count > 0)
            {
                sb.AppendLine("    Extra accent markers (from active lenses):");
                foreach (var m in extraAccent) sb.AppendLine($"      - {m}");
            }
            return sb.ToString().TrimEnd();
        }

        // ---------------------------------------------------------------
        // Internals
        // ---------------------------------------------------------------

        private bool HasLens(string lensId)
        {
            if (string.IsNullOrEmpty(lensId)) return false;
            foreach (var l in lenses) if (l.id == lensId) return true;
            return false;
        }
    }
}
