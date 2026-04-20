// NpcForgePersonality.cs
//
// Runtime mirror of Python's v0.18.0 Personality / OCEAN schema.
// Big-5 personality vector as a foundation register-hint layer
// beneath voice, lenses, ethics, and trajectory. Composes additively
// with every other active block.
//
// Authoring: drop this component on an NPC GameObject, set the five
// sliders, and call SummarizeForPrompt() when assembling the improv
// prompt. The output shape matches Python's _render_personality
// line-for-line so a single NPC's prompt is byte-identical whether
// composed by the Python CLI or by the Unity client.

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace Altai.NpcForge
{
    [Serializable]
    public class NpcForgeOceanProfile
    {
        [Range(0f, 1f)] public float openness = 0.5f;
        [Range(0f, 1f)] public float conscientiousness = 0.5f;
        [Range(0f, 1f)] public float extraversion = 0.5f;
        [Range(0f, 1f)] public float agreeableness = 0.5f;
        [Range(0f, 1f)] public float neuroticism = 0.5f;

        public float Axis(string name)
        {
            switch (name)
            {
                case "openness": return openness;
                case "conscientiousness": return conscientiousness;
                case "extraversion": return extraversion;
                case "agreeableness": return agreeableness;
                case "neuroticism": return neuroticism;
                default: return 0.5f;
            }
        }

        /// <summary>Axes with |value - 0.5| >= band, most distinctive
        /// first. Returns tuples of (axisName, "high"|"low", distance).</summary>
        public List<(string axis, string direction, float distance)> DominantAxes(
            int topN = 2, float band = 0.25f)
        {
            var scored = new List<(string, string, float)>();
            string[] names = {
                "openness", "conscientiousness", "extraversion",
                "agreeableness", "neuroticism",
            };
            foreach (var n in names)
            {
                float v = Axis(n);
                float delta = v - 0.5f;
                if (Mathf.Abs(delta) < band) continue;
                scored.Add((n, delta > 0 ? "high" : "low", Mathf.Abs(delta)));
            }
            scored.Sort((a, b) => b.Item3.CompareTo(a.Item3));
            if (topN > 0 && scored.Count > topN) scored = scored.GetRange(0, topN);
            return scored;
        }
    }

    public class NpcForgePersonality : MonoBehaviour
    {
        [Tooltip("OCEAN personality profile. Default (all 0.5) is " +
                 "intentionally bland — pick distinctive values for the " +
                 "rendered block to actually appear in the prompt.")]
        [SerializeField] private NpcForgeOceanProfile profile
            = new NpcForgeOceanProfile();

        [Tooltip("Axes outside this distance from 0.5 count as " +
                 "distinctive. 0.25 matches Python's default band.")]
        [SerializeField, Range(0.05f, 0.5f)] private float distinctiveBand = 0.25f;

        [Tooltip("Maximum distinctive axes to render.")]
        [SerializeField, Min(1)] private int topNAxes = 2;

        public NpcForgeOceanProfile Profile => profile;

        // ---------------------------------------------------------------
        // Register-hint prose — mirror of Python's _OCEAN_PROSE
        // ---------------------------------------------------------------

        private static readonly Dictionary<string, string> _hints = new()
        {
            ["openness|high"] = "entertains strange ideas and speculative claims; willing to follow a line of thought wherever it goes",
            ["openness|low"] = "pragmatic and grounded; dismisses abstractions and 'what if' lines of thought",
            ["conscientiousness|high"] = "precise in speech, plans ahead, rarely forgets a detail once spoken; finishes sentences",
            ["conscientiousness|low"] = "impulsive, casual in speech, drops threads mid-sentence, does not notice when a promise goes unkept",
            ["extraversion|high"] = "chatty; volunteers information without being asked; opens follow-up questions; pace is energetic",
            ["extraversion|low"] = "terse; waits to be asked; closes conversations early; pace is slow and spare",
            ["agreeableness|high"] = "warm toward the person in front of them; cooperative; softens hard news with phrasing",
            ["agreeableness|low"] = "blunt; does not soften; confrontational when pressed; willing to disagree directly",
            ["neuroticism|high"] = "emotionally reactive; anger, anxiety, and sadness surface quickly and show in register",
            ["neuroticism|low"] = "even-keeled; slow to flinch; emotional shifts are small and understated",
        };

        /// <summary>Render the OCEAN block for injection into the improv
        /// system prompt. Byte-compatible with Python's
        /// _render_personality output. Empty string for null / neutral
        /// profiles so the caller can concatenate safely.</summary>
        public string SummarizeForPrompt()
        {
            var dominant = profile.DominantAxes(topN: topNAxes, band: distinctiveBand);
            if (dominant.Count == 0) return string.Empty;

            var sb = new StringBuilder();
            sb.AppendLine(
                "Personality profile (OCEAN register hints — shape pacing, "
                + "warmth, volatility; compose with voice + lenses; never narrate):");
            foreach (var (axis, direction, _) in dominant)
            {
                string key = $"{axis}|{direction}";
                string prose = _hints.TryGetValue(key, out var p)
                    ? p : $"{direction} {axis}";
                float val = profile.Axis(axis);
                sb.AppendLine($"- {axis} ({direction}, {val:F2}): {prose}");
            }
            return sb.ToString().TrimEnd();
        }
    }
}
