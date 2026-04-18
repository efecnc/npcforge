// NpcForgePreferences.cs
//
// Per-user, per-project settings stored in EditorPrefs so they survive
// editor restarts and are not committed to source control. Keys are
// prefixed with the Unity project's PlayerSettings.productGUID so two
// Unity projects on the same machine keep their own npcforge paths.

using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    internal static class NpcForgePreferences
    {
        private const string KeyPrefix = "Altai.NpcForge.";

        public static string NpcforgePath
        {
            get => EditorPrefs.GetString(Scoped("NpcforgePath"), "npcforge");
            set => EditorPrefs.SetString(Scoped("NpcforgePath"), value);
        }

        public static string DemoDir
        {
            get => EditorPrefs.GetString(Scoped("DemoDir"), "");
            set => EditorPrefs.SetString(Scoped("DemoDir"), value);
        }

        public static string GeminiApiKey
        {
            get => EditorPrefs.GetString(Scoped("GeminiApiKey"), "");
            set => EditorPrefs.SetString(Scoped("GeminiApiKey"), value);
        }

        public static bool InstallScriptsOnFirstSync
        {
            get => EditorPrefs.GetBool(Scoped("InstallScripts"), true);
            set => EditorPrefs.SetBool(Scoped("InstallScripts"), value);
        }

        private static string Scoped(string key)
        {
            // Scope to the current Unity project so two projects on the
            // same machine don't stomp each other's paths.
            string project = PlayerSettings.productGUID.ToString();
            return $"{KeyPrefix}{project}.{key}";
        }
    }
}
