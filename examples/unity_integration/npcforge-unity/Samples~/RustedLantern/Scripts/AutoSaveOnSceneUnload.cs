// AutoSaveOnSceneUnload.cs
//
// Sample script — demonstrates how to call NpcForgeSaveLoad.Save() at
// scene-teardown time so a player's dialogue state survives scene
// changes and application quits without explicit save buttons.
//
// For single-player story games this is usually what you want: treat
// save/load like modern adventure games do (auto on exit, explicit
// named slots on demand).

using UnityEngine;

namespace Altai.NpcForge.Samples.RustedLantern
{
    [RequireComponent(typeof(NpcForgeSaveLoad))]
    public class AutoSaveOnSceneUnload : MonoBehaviour
    {
        [Tooltip("Save when this GameObject gets destroyed (scene unload, " +
                 "application quit).")]
        [SerializeField] private bool saveOnDestroy = true;

        [Tooltip("Save when the application pauses — important for " +
                 "mobile where OnDestroy can be skipped on a forced kill.")]
        [SerializeField] private bool saveOnPause = true;

        private NpcForgeSaveLoad _save;

        private void Awake()
        {
            _save = GetComponent<NpcForgeSaveLoad>();
        }

        private void OnApplicationPause(bool paused)
        {
            if (paused && saveOnPause) _save.Save();
        }

        private void OnApplicationQuit()
        {
            if (saveOnDestroy) _save.Save();
        }

        private void OnDestroy()
        {
            if (!Application.isPlaying) return;
            if (saveOnDestroy) _save.Save();
        }
    }
}
