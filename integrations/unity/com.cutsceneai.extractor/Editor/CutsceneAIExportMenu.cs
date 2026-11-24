using System;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.Timeline;

namespace CutsceneAI.UnityExtractor
{
    internal static class CutsceneAIExportMenu
    {
        private const string MenuPath = "Tools/CutsceneAI/Export Selected Timeline";

        [MenuItem("Tools/CutsceneAI/Export for Studio", priority = 80)]
        private static void ExportForStudio()
        {
            var director = GetSelectedDirector();
            if (director == null || string.IsNullOrEmpty(director.gameObject.scene.path)
                || director.gameObject.scene.isDirty || EditorUtility.IsDirty(director.playableAsset)
                || EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorUtility.DisplayDialog("CutScene Studio",
                    "Save the scene and Timeline, exit Play Mode, and select its PlayableDirector.", "OK");
                return;
            }

            string output = null;
            try
            {
                output = UnityTimelineExtractor.Export(director, unique: true);
                UnityTimelineOffsetAugmenter.Augment(output, director);
                var census = CutSceneAIFeatureSurfaceScanner.ExportCensus();
                Debug.Log("[CutScene Studio] Export complete: " + output + " | Source details: " + census);
                EditorUtility.RevealInFinder(output);
            }
            catch (Exception exception)
            {
                if (output != null && File.Exists(output))
                    File.Delete(output);
                Debug.LogException(exception);
                EditorUtility.DisplayDialog("Export failed", exception.Message, "OK");
            }
        }

        [MenuItem(MenuPath, priority = 100)]
        private static void ExportSelectedTimeline()
        {
            var director = GetSelectedDirector();
            if (director == null)
            {
                EditorUtility.DisplayDialog(
                    "CutsceneAI",
                    "Select a GameObject containing a PlayableDirector with a saved TimelineAsset.",
                    "OK");
                return;
            }

            try
            {
                var outputPath = UnityTimelineExtractor.Export(director);
                UnityTimelineOffsetAugmenter.Augment(outputPath, director);
                Debug.Log($"[CutsceneAI] Timeline exported to: {outputPath}");
                EditorUtility.RevealInFinder(outputPath);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                EditorUtility.DisplayDialog("CutsceneAI Export Failed", exception.Message, "OK");
            }
        }

        [MenuItem(MenuPath, validate = true)]
        private static bool ValidateExportSelectedTimeline()
        {
            return GetSelectedDirector() != null;
        }

        private static PlayableDirector GetSelectedDirector()
        {
            var gameObject = Selection.activeGameObject;
            if (gameObject == null)
                return null;

            var director = gameObject.GetComponent<PlayableDirector>();
            if (director == null)
                return null;

            return director.playableAsset is TimelineAsset ? director : null;
        }
    }
}
