// NpcForgeYarnParser.cs
//
// Minimal Yarn Spinner 2 parser — a C# port of the Python ``npcforge.play``
// parser. Covers exactly the subset of syntax npcforge itself emits:
//
//   title: ...
//   tags: ...
//   ---
//   Speaker: text                         (narration + dialogue)
//   -> [label] / -> label                 (options)
//   <<jump NodeName>>                     (jumps inside options)
//   <<if visited_count("X") % N == I>>    (bark rotation)
//   <<if visited_count("X") == I>>        (repeat-greeting)
//   <<if $var == "value">>                (enum greeting)
//   <<else>> / <<endif>>
//   ===
//
// Anything else is ignored. This exists so the in-Editor Dialogue Preview
// window can step through generated .yarn files without entering Play
// mode — pure data, no Yarn runtime needed.

using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Altai.NpcForge.Editor
{
    public class YarnLine
    {
        public string Speaker;
        public string Text;
        public override string ToString() =>
            string.IsNullOrEmpty(Speaker) ? Text : $"{Speaker}: {Text}";
    }

    public class YarnOption
    {
        public string Label;
        public readonly List<YarnLine> Lines = new List<YarnLine>();
        public string JumpTo;
    }

    public class YarnEnumVariant
    {
        public string Variable;
        public string Value;
        public YarnLine Line;
    }

    public class YarnVisitVariant
    {
        public int VisitIndex; // -1 = else fallback
        public YarnLine Line;
    }

    public class YarnNode
    {
        public string Title;
        public readonly List<string> Tags = new List<string>();
        public readonly List<YarnLine> Preamble = new List<YarnLine>();
        public readonly List<YarnOption> Options = new List<YarnOption>();
        public readonly List<YarnLine> BarkVariants = new List<YarnLine>();
        public readonly List<YarnEnumVariant> EnumVariants = new List<YarnEnumVariant>();
        public readonly List<YarnVisitVariant> VisitVariants = new List<YarnVisitVariant>();

        /// <summary>Best-effort node kind based on structure. Drives the
        /// Dialogue Preview window's renderer selection.</summary>
        public enum Kind { WalkUp, Bark, EnumGreeting, RepeatGreeting, WorldStart, Plain }

        public Kind DetectKind()
        {
            if (BarkVariants.Count > 0) return Kind.Bark;
            if (EnumVariants.Count > 0) return Kind.EnumGreeting;
            if (VisitVariants.Count > 0) return Kind.RepeatGreeting;
            if (Options.Count > 0) return Kind.WalkUp;
            if (!string.IsNullOrEmpty(Title) && Title.Equals("Start",
                System.StringComparison.OrdinalIgnoreCase)) return Kind.WorldStart;
            return Kind.Plain;
        }
    }

    public static class NpcForgeYarnParser
    {
        // Regexes mirror play.py exactly so behavior stays in lock-step with
        // the Python-side CLI preview.
        private static readonly Regex _title = new Regex(@"^title:\s*(.+?)\s*$");
        private static readonly Regex _tags = new Regex(@"^tags:\s*(.+?)\s*$");
        private static readonly Regex _option = new Regex(@"^->\s*\[(.+?)\]\s*$");
        private static readonly Regex _bareOption = new Regex(@"^->\s*(.+?)\s*$");
        private static readonly Regex _jump = new Regex(@"^\s*<<jump\s+([^>\s]+)>>\s*$");
        private static readonly Regex _ifCounter = new Regex(
            "^<<(?:else)?if\\s+visited_count\\(\\s*\"(?<node>[^\"]+)\"\\s*\\)\\s*%\\s*(?<mod>\\d+)\\s*==\\s*(?<idx>\\d+)\\s*>>");
        private static readonly Regex _ifVisit = new Regex(
            "^<<(?:else)?if\\s+visited_count\\(\\s*\"(?<node>[^\"]+)\"\\s*\\)\\s*==\\s*(?<idx>\\d+)\\s*>>");
        private static readonly Regex _ifEnum = new Regex(
            "^<<(?:else)?if\\s+\\$(?<var>\\w+)\\s*==\\s*\"(?<value>[^\"]+)\"\\s*>>\\s*$");
        private static readonly Regex _else = new Regex(@"^<<else>>\s*$");
        private static readonly Regex _endif = new Regex(@"^<<endif>>\s*$");
        private static readonly Regex _speaker = new Regex(
            @"^(?<speaker>[^:/][^:]*?):\s*(?<text>.+?)\s*$");

        public static List<YarnNode> Parse(string text)
        {
            var nodes = new List<YarnNode>();
            YarnNode current = null;
            YarnOption currentOption = null;
            bool inHeader = false;
            bool inBody = false;

            if (text == null) return nodes;
            string[] lines = text.Replace("\r\n", "\n").Split('\n');

            int i = 0;
            while (i < lines.Length)
            {
                string raw = lines[i];
                string stripped = raw.Trim();

                if (stripped == "===")
                {
                    if (current != null) nodes.Add(current);
                    current = null;
                    currentOption = null;
                    inHeader = false;
                    inBody = false;
                    i++;
                    continue;
                }

                if (current == null)
                {
                    var m = _title.Match(stripped);
                    if (m.Success)
                    {
                        current = new YarnNode { Title = m.Groups[1].Value };
                        inHeader = true;
                    }
                    i++;
                    continue;
                }

                if (inHeader)
                {
                    if (stripped == "---") { inHeader = false; inBody = true; i++; continue; }
                    var mt = _tags.Match(stripped);
                    if (mt.Success)
                    {
                        foreach (string t in mt.Groups[1].Value.Split(','))
                            current.Tags.Add(t.Trim());
                    }
                    i++;
                    continue;
                }

                if (inBody)
                {
                    if (_endif.IsMatch(stripped)) { i++; continue; }
                    if (_else.IsMatch(stripped))
                    {
                        var scoop = ScoopSpeaker(lines, i);
                        if (scoop != null && current.VisitVariants.Count > 0)
                        {
                            current.VisitVariants.Add(new YarnVisitVariant
                            {
                                VisitIndex = -1,
                                Line = scoop.Item1,
                            });
                            i = scoop.Item2;
                            continue;
                        }
                        i++;
                        continue;
                    }

                    var cond = MatchConditional(stripped);
                    if (cond != null)
                    {
                        var scoop = ScoopSpeaker(lines, i);
                        if (scoop != null)
                        {
                            string kind = cond.Item1;
                            var caps = cond.Item2;
                            if (kind == "counter")
                                current.BarkVariants.Add(scoop.Item1);
                            else if (kind == "visit")
                                current.VisitVariants.Add(new YarnVisitVariant
                                {
                                    VisitIndex = int.Parse(caps["idx"]),
                                    Line = scoop.Item1,
                                });
                            else if (kind == "enum")
                                current.EnumVariants.Add(new YarnEnumVariant
                                {
                                    Variable = caps["var"],
                                    Value = caps["value"],
                                    Line = scoop.Item1,
                                });
                            i = scoop.Item2;
                            continue;
                        }
                        i++;
                        continue;
                    }

                    var mopt = _option.Match(stripped);
                    if (!mopt.Success) mopt = _bareOption.Match(stripped);
                    if (mopt.Success)
                    {
                        currentOption = new YarnOption { Label = mopt.Groups[1].Value.Trim() };
                        current.Options.Add(currentOption);
                        i++;
                        continue;
                    }

                    var mjump = _jump.Match(raw);
                    if (mjump.Success)
                    {
                        if (currentOption != null)
                            currentOption.JumpTo = mjump.Groups[1].Value;
                        i++;
                        continue;
                    }

                    var ms = _speaker.Match(stripped);
                    if (ms.Success)
                    {
                        var line = new YarnLine
                        {
                            Speaker = ms.Groups["speaker"].Value.Trim(),
                            Text = StripTrailingComment(ms.Groups["text"].Value),
                        };
                        if (currentOption != null) currentOption.Lines.Add(line);
                        else current.Preamble.Add(line);
                        i++;
                        continue;
                    }

                    // Narration / unrecognised at node scope.
                    if (currentOption == null
                        && !string.IsNullOrEmpty(stripped)
                        && !stripped.StartsWith("//")
                        && !stripped.StartsWith("<<"))
                    {
                        current.Preamble.Add(new YarnLine { Speaker = string.Empty, Text = stripped });
                    }
                    i++;
                    continue;
                }

                i++;
            }

            if (current != null) nodes.Add(current);
            return nodes;
        }

        private static System.Tuple<string, Dictionary<string, string>> MatchConditional(string stripped)
        {
            Match m;
            m = _ifCounter.Match(stripped);
            if (m.Success) return System.Tuple.Create("counter", CapturesOf(m));
            m = _ifVisit.Match(stripped);
            if (m.Success) return System.Tuple.Create("visit", CapturesOf(m));
            m = _ifEnum.Match(stripped);
            if (m.Success) return System.Tuple.Create("enum", CapturesOf(m));
            return null;
        }

        private static readonly string[] _namedCaptures = { "node", "mod", "idx", "var", "value" };

        private static Dictionary<string, string> CapturesOf(Match m)
        {
            // Named groups across our conditional regexes: node, mod, idx,
            // var, value. Iterating a fixed list avoids depending on
            // GroupCollection's by-name iterator (which is available on
            // modern .NET but not universally across Unity's scripting
            // runtimes).
            var d = new Dictionary<string, string>();
            foreach (string n in _namedCaptures)
            {
                var g = m.Groups[n];
                if (g != null && g.Success) d[n] = g.Value;
            }
            return d;
        }

        private static System.Tuple<YarnLine, int> ScoopSpeaker(string[] lines, int i)
        {
            if (i + 1 >= lines.Length) return null;
            var ms = _speaker.Match(lines[i + 1].Trim());
            if (!ms.Success) return null;
            return System.Tuple.Create(
                new YarnLine
                {
                    Speaker = ms.Groups["speaker"].Value.Trim(),
                    Text = StripTrailingComment(ms.Groups["text"].Value),
                },
                i + 2);
        }

        private static string StripTrailingComment(string text)
        {
            int idx = text.IndexOf("  //", System.StringComparison.Ordinal);
            if (idx == -1) idx = text.IndexOf(" //", System.StringComparison.Ordinal);
            if (idx != -1) return text.Substring(0, idx).TrimEnd();
            return text;
        }
    }
}
