// NpcForgeRelationshipGraphWindow.cs
//
// Plain-IMGUI graph view of the cast's relationship network.
//
// Reads NpcForgeYamlReader's summaries, arranges each NPC around a
// circle (deterministic, by id-sort order so subsequent opens look the
// same), and draws an arrow for every declared relationship. Clicking
// a node filters edges to "incident on this NPC"; clicking background
// clears the filter.
//
// We use Handles.DrawBezier for curved edges — they read better than
// straight lines when two NPCs have mutual but different opinions (the
// curves separate A→B from B→A visually).

using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    public class NpcForgeRelationshipGraphWindow : EditorWindow
    {
        private List<NpcSummary> _npcs = new List<NpcSummary>();
        private string _focusedId;          // null = no filter
        private Vector2 _pan;
        private float _zoom = 1f;
        private string _search = string.Empty;

        private const float NodeRadius = 44f;
        private const float GraphRadius = 240f;

        [MenuItem("Tools/npcforge/Relationship Graph...", priority = 23)]
        public static void Open()
        {
            var wnd = GetWindow<NpcForgeRelationshipGraphWindow>();
            wnd.titleContent = new GUIContent("npcforge Graph");
            wnd.minSize = new Vector2(640, 520);
            wnd.Reload();
            wnd.Show();
        }

        private void OnFocus() => Reload();

        private void Reload()
        {
            _npcs = NpcForgeYamlReader.LoadSummaries(NpcForgePreferences.DemoDir);
            _npcs.Sort((a, b) => string.CompareOrdinal(a.Id, b.Id));
            if (_focusedId != null && !_npcs.Exists(n => n.Id == _focusedId))
                _focusedId = null;
        }

        private void OnGUI()
        {
            DrawToolbar();
            DrawGraphCanvas();
        }

        private void DrawToolbar()
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                GUILayout.Label($"NPCs: {_npcs.Count}", EditorStyles.toolbarButton);
                if (GUILayout.Button("Refresh", EditorStyles.toolbarButton, GUILayout.Width(70)))
                    Reload();
                GUILayout.Space(8);
                EditorGUILayout.LabelField("Search", GUILayout.Width(50));
                _search = EditorGUILayout.TextField(_search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(140));
                GUILayout.FlexibleSpace();

                if (_focusedId != null)
                {
                    if (GUILayout.Button($"Focus: {_focusedId} (×)",
                            EditorStyles.toolbarButton, GUILayout.MaxWidth(220)))
                    {
                        _focusedId = null;
                    }
                }
                EditorGUILayout.LabelField($"Zoom {_zoom:0.00}",
                    EditorStyles.miniLabel, GUILayout.Width(70));
            }
        }

        private void DrawGraphCanvas()
        {
            if (_npcs.Count == 0)
            {
                EditorGUILayout.HelpBox(
                    "No characters.yaml found. Set the npcforge project directory " +
                    "in Tools → npcforge → Open Panel…",
                    MessageType.Info);
                return;
            }

            // Reserve a rect for the graph area.
            var r = GUILayoutUtility.GetRect(
                position.width, position.height - 24f, GUILayout.ExpandHeight(true));
            GUI.Box(r, GUIContent.none, EditorStyles.helpBox);

            HandleInput(r);

            Vector2 center = r.center + _pan;
            float radius = Mathf.Min(r.width, r.height) * 0.5f * 0.72f * _zoom;
            radius = Mathf.Max(120f, radius);

            // Layout NPCs on a circle (deterministic by list order).
            var pos = new Dictionary<string, Vector2>(_npcs.Count);
            for (int i = 0; i < _npcs.Count; i++)
            {
                float a = (i / (float)_npcs.Count) * Mathf.PI * 2f - Mathf.PI / 2f;
                pos[_npcs[i].Id] = center + new Vector2(
                    Mathf.Cos(a) * radius, Mathf.Sin(a) * radius);
            }

            // Edges first so nodes render on top.
            Handles.BeginGUI();
            DrawEdges(pos);
            Handles.EndGUI();

            DrawNodes(pos);
            DrawLegend(r);
        }

        private void DrawEdges(Dictionary<string, Vector2> pos)
        {
            foreach (var npc in _npcs)
            {
                if (!pos.TryGetValue(npc.Id, out Vector2 from)) continue;
                foreach (var rel in npc.Relationships)
                {
                    string targetId = rel.Key;
                    if (!pos.TryGetValue(targetId, out Vector2 to)) continue;
                    if (_focusedId != null && _focusedId != npc.Id && _focusedId != targetId)
                        continue;

                    Color c = GuessRelationshipColor(rel.Value);
                    Vector2 dir = (to - from).normalized;
                    // Pull the endpoints back so arrows don't dive into the
                    // circle nodes — the edge should kiss the node's rim.
                    Vector2 start = from + dir * NodeRadius;
                    Vector2 end = to - dir * NodeRadius;
                    Vector2 perp = new Vector2(-dir.y, dir.x);

                    // Curve asymmetrically so A→B and B→A don't overlap.
                    float curve = 48f;
                    Vector2 startTangent = start + perp * curve + dir * 40f;
                    Vector2 endTangent = end + perp * curve - dir * 40f;

                    Handles.DrawBezier(start, end, startTangent, endTangent, c, null, 2.2f);

                    // Arrowhead (simple triangle).
                    Vector2 ah = (end - endTangent).normalized;
                    Vector2 ahR = new Vector2(-ah.y, ah.x);
                    Handles.color = c;
                    Handles.DrawAAConvexPolygon(
                        end,
                        end - ah * 10f + ahR * 5f,
                        end - ah * 10f - ahR * 5f);

                    // Midpoint label.
                    Vector2 mid = (start + end) * 0.5f + perp * 18f;
                    var label = new GUIContent(TrimLabel(rel.Value));
                    var size = EditorStyles.miniLabel.CalcSize(label);
                    GUI.Label(new Rect(mid.x - size.x * 0.5f, mid.y - size.y * 0.5f,
                        size.x + 4f, size.y), label, EditorStyles.miniLabel);
                }
            }
        }

        private static string TrimLabel(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            if (s.Length > 38) return s.Substring(0, 36) + "…";
            return s;
        }

        private static readonly Color _positive = new Color(0.45f, 0.8f, 0.5f);
        private static readonly Color _neutral = new Color(0.7f, 0.7f, 0.7f);
        private static readonly Color _negative = new Color(0.85f, 0.45f, 0.4f);

        /// <summary>Colour hint inferred from the stringly-typed opinion
        /// text. Not authoritative — it's a first pass so hostile edges
        /// stand out from protective ones at a glance.</summary>
        private static Color GuessRelationshipColor(string text)
        {
            if (string.IsNullOrEmpty(text)) return _neutral;
            string t = text.ToLowerInvariant();
            if (t.Contains("hostile") || t.Contains("hate") || t.Contains("afraid")
                || t.Contains("fear") || t.Contains("distrust") || t.Contains("rival"))
                return _negative;
            if (t.Contains("protective") || t.Contains("loves") || t.Contains("loyal")
                || t.Contains("ally") || t.Contains("trust") || t.Contains("friend")
                || t.Contains("admire"))
                return _positive;
            return _neutral;
        }

        private void DrawNodes(Dictionary<string, Vector2> pos)
        {
            string filter = string.IsNullOrEmpty(_search) ? null : _search.ToLowerInvariant();
            foreach (var npc in _npcs)
            {
                if (!pos.TryGetValue(npc.Id, out Vector2 p)) continue;
                bool matches = filter == null || npc.Matches(filter);
                bool focused = _focusedId == npc.Id;

                var rect = new Rect(p.x - NodeRadius, p.y - NodeRadius,
                    NodeRadius * 2f, NodeRadius * 2f);

                Color prev = GUI.backgroundColor;
                GUI.backgroundColor = focused
                    ? new Color(1f, 0.9f, 0.3f)
                    : (matches ? new Color(0.8f, 0.85f, 0.95f)
                               : new Color(0.55f, 0.55f, 0.55f));
                if (GUI.Button(rect, GUIContent.none))
                {
                    _focusedId = focused ? null : npc.Id;
                }
                GUI.backgroundColor = prev;

                var label = new GUIContent(npc.Id,
                    $"{npc.Name} — {npc.Role}\nMotivations: {string.Join(", ", npc.Motivations)}");
                var style = new GUIStyle(EditorStyles.miniBoldLabel)
                {
                    alignment = TextAnchor.MiddleCenter,
                    wordWrap = true,
                };
                GUI.Label(rect, label, style);
            }
        }

        private void DrawLegend(Rect r)
        {
            var rect = new Rect(r.xMin + 10f, r.yMax - 64f, 220f, 54f);
            GUI.Box(rect, GUIContent.none, EditorStyles.helpBox);
            using (new GUILayout.AreaScope(rect))
            {
                EditorGUILayout.LabelField("Edge colour", EditorStyles.miniBoldLabel);
                using (new GUILayout.HorizontalScope())
                {
                    DrawSwatch(_positive, "ally / loves / trust");
                    DrawSwatch(_negative, "hostile / fear");
                    DrawSwatch(_neutral, "neutral");
                }
            }
        }

        private static void DrawSwatch(Color c, string label)
        {
            Color prev = GUI.color;
            GUI.color = c;
            GUILayout.Label("●", GUILayout.Width(14));
            GUI.color = prev;
            GUILayout.Label(label, EditorStyles.miniLabel, GUILayout.MinWidth(90));
        }

        private void HandleInput(Rect canvas)
        {
            Event e = Event.current;
            if (!canvas.Contains(e.mousePosition)) return;

            if (e.type == EventType.ScrollWheel)
            {
                _zoom = Mathf.Clamp(_zoom - e.delta.y * 0.05f, 0.4f, 2.0f);
                e.Use();
                Repaint();
            }
            if (e.type == EventType.MouseDrag && e.button == 2)
            {
                _pan += e.delta;
                e.Use();
                Repaint();
            }
        }
    }
}
