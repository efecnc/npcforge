// NpcForgeCliRunner.cs
//
// Thin wrapper around System.Diagnostics.Process for invoking the
// npcforge CLI from the Editor. Captures stdout + stderr, surfaces
// exit codes, and runs the actual subprocess on a background thread so
// the Editor UI stays responsive.
//
// Why not async/await everywhere? Because the Unity Editor needs UI
// updates on the main thread, and System.Diagnostics.Process's async
// output handlers fire on whichever thread the runtime picks. We use a
// short-lived Thread + main-thread callback via EditorApplication.delayCall.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Altai.NpcForge.Editor
{
    /// <summary>Callback fired on the Unity main thread when a CLI run finishes.</summary>
    public delegate void NpcForgeCliCompleted(int exitCode, string stdout, string stderr);

    /// <summary>Callback fired on the main thread for each captured stderr/stdout line.</summary>
    public delegate void NpcForgeCliOutputLine(string line);

    public static class NpcForgeCliRunner
    {
        /// <summary>Run the npcforge CLI with the given arguments in a background thread.
        /// Invokes <paramref name="onComplete"/> on the main thread when done.</summary>
        public static void RunAsync(
            string[] arguments,
            Dictionary<string, string> environmentExtras,
            NpcForgeCliCompleted onComplete,
            NpcForgeCliOutputLine onOutputLine = null)
        {
            var thread = new System.Threading.Thread(() =>
            {
                int exit = -1;
                var stdout = new StringBuilder();
                var stderr = new StringBuilder();

                try
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = NpcForgePreferences.NpcforgePath,
                        Arguments = QuoteArgs(arguments),
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WorkingDirectory = string.IsNullOrEmpty(NpcForgePreferences.DemoDir)
                            ? Directory.GetCurrentDirectory()
                            : NpcForgePreferences.DemoDir,
                    };

                    if (environmentExtras != null)
                    {
                        foreach (var kv in environmentExtras)
                        {
                            if (!string.IsNullOrEmpty(kv.Value))
                            {
                                psi.EnvironmentVariables[kv.Key] = kv.Value;
                            }
                        }
                    }

                    using (var proc = new Process { StartInfo = psi, EnableRaisingEvents = true })
                    {
                        proc.OutputDataReceived += (s, e) =>
                        {
                            if (e.Data == null) return;
                            stdout.AppendLine(e.Data);
                            if (onOutputLine != null)
                            {
                                MainThreadDispatch(() => onOutputLine(e.Data));
                            }
                        };
                        proc.ErrorDataReceived += (s, e) =>
                        {
                            if (e.Data == null) return;
                            stderr.AppendLine(e.Data);
                            if (onOutputLine != null)
                            {
                                MainThreadDispatch(() => onOutputLine(e.Data));
                            }
                        };

                        proc.Start();
                        proc.BeginOutputReadLine();
                        proc.BeginErrorReadLine();
                        proc.WaitForExit();
                        exit = proc.ExitCode;
                    }
                }
                catch (Exception ex)
                {
                    stderr.AppendLine($"[NpcForge] failed to run CLI: {ex.Message}");
                }

                int finalExit = exit;
                string finalOut = stdout.ToString();
                string finalErr = stderr.ToString();
                MainThreadDispatch(() => onComplete?.Invoke(finalExit, finalOut, finalErr));
            });

            thread.IsBackground = true;
            thread.Start();

            // Show a progress bar that reflects "running" — canceling it only
            // clears the bar; the subprocess continues to completion. Callers
            // can add a real cancel path later if needed.
            try
            {
                string label = $"npcforge {string.Join(" ", arguments)}";
                EditorUtility.DisplayProgressBar("npcforge", label, 0.5f);
            }
            catch { /* running headless — ignore */ }
        }

        /// <summary>Fire a callback on the Unity Editor main thread.</summary>
        private static void MainThreadDispatch(Action action)
        {
            if (action == null) return;
            EditorApplication.delayCall += () => action();
        }

        /// <summary>Shell-safe quoting for the argv list.</summary>
        private static string QuoteArgs(string[] args)
        {
            if (args == null || args.Length == 0) return string.Empty;
            var parts = new List<string>(args.Length);
            foreach (string a in args)
            {
                if (string.IsNullOrEmpty(a)) continue;
                if (a.Contains(" ") || a.Contains("\""))
                {
                    parts.Add("\"" + a.Replace("\"", "\\\"") + "\"");
                }
                else
                {
                    parts.Add(a);
                }
            }
            return string.Join(" ", parts);
        }
    }
}
