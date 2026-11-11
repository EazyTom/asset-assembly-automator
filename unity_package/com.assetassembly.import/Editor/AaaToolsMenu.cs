#if UNITY_EDITOR
using System.IO;
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    public static class AaaToolsMenu
    {
        [MenuItem("AAA Tools/Build Flight Rig (Selected)", false, 10)]
        static void BuildFlightRig()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                if (selected.GetComponentInParent<FlightController>() != null)
                {
                    Debug.LogWarning($"{selected.name} is already inside a flight rig.", selected);
                    continue;
                }

                GameObject rig = FlightRigBuilder.Build(selected);
                Debug.Log($"Built AAA Aircraft flight rig '{rig.name}'.", rig);
            }
        }

        [MenuItem("AAA Tools/Build Flight Rig (Selected)", true)]
        static bool BuildFlightRigValidate() => HasRendererSelection();

        [MenuItem("AAA Tools/Build Drive Rig (Selected)", false, 11)]
        static void BuildDriveRig()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                if (selected.GetComponentInParent<DriveController>() != null)
                {
                    Debug.LogWarning($"{selected.name} is already inside a drive rig.", selected);
                    continue;
                }

                GameObject rig = DriveRigBuilder.Build(selected);
                Debug.Log($"Built {AaaLabels.Vehicle} drive rig '{rig.name}'.", rig);
            }
        }

        [MenuItem("AAA Tools/Build Drive Rig (Selected)", true)]
        static bool BuildDriveRigValidate() => HasRendererSelection();

        [MenuItem("AAA Tools/Replace Steering Wheel (Selected Drive Rig)", false, 12)]
        static void ReplaceSteeringWheelMenu()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                DriveController drive = selected.GetComponent<DriveController>();
                if (drive == null)
                {
                    drive = selected.GetComponentInParent<DriveController>();
                }

                if (drive == null)
                {
                    continue;
                }

                GameObject wheel = DriveRigBuilder.ReplaceSteeringWheel(drive);
                if (wheel != null)
                {
                    Debug.Log($"Replaced steering wheel on '{drive.name}' with Neon Command Wheel.", wheel);
                }
            }
        }

        [MenuItem("AAA Tools/Replace Steering Wheel (Selected Drive Rig)", true)]
        static bool ReplaceSteeringWheelValidate()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                if (selected.GetComponent<DriveController>() != null ||
                    selected.GetComponentInParent<DriveController>() != null)
                {
                    return true;
                }
            }

            return false;
        }

        [MenuItem("AAA Tools/Fix Drive Orientation (Selected Drive Rig)", false, 13)]
        static void FixDriveOrientation()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                DriveController drive = selected.GetComponent<DriveController>()
                    ?? selected.GetComponentInParent<DriveController>();
                if (drive == null)
                {
                    continue;
                }

                Undo.RegisterFullObjectHierarchyUndo(drive.gameObject, "Fix Drive Orientation");
                Undo.RecordObject(drive, "Fix Drive Orientation");
                bool flattened = drive.FlattenRootToYaw();
                bool turned = drive.AlignNoseToLongestAxis();
                drive.DeriveWheelAnchorsFromBounds();
                drive.ApplySteeringWheelTransform();
                drive.SyncDashboardPanelTransform();
                EditorUtility.SetDirty(drive);
                Debug.Log(
                    $"[{AaaLabels.Vehicle}] Fixed orientation on '{drive.name}': " +
                    $"root flattened={flattened}, nose quarter-turned={turned}.",
                    drive);
            }
        }

        [MenuItem("AAA Tools/Fix Drive Orientation (Selected Drive Rig)", true)]
        static bool FixDriveOrientationValidate() => ReplaceSteeringWheelValidate();

        [MenuItem("AAA Tools/Fit Drive Hull To 4.2m (Selected Drive Rig)", false, 14)]
        static void FitDriveHull()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                DriveController drive = selected.GetComponent<DriveController>()
                    ?? selected.GetComponentInParent<DriveController>();
                if (drive == null)
                {
                    continue;
                }

                bool changed = DriveRigBuilder.FitHullToLength(drive);
                Debug.Log(
                    changed
                        ? $"[{AaaLabels.Vehicle}] Fitted '{drive.name}' hull to {DriveRigBuilder.DefaultTargetMeters:F1}m and re-derived placements."
                        : $"[{AaaLabels.Vehicle}] '{drive.name}' already within 1% of {DriveRigBuilder.DefaultTargetMeters:F1}m.",
                    drive);
            }
        }

        [MenuItem("AAA Tools/Fit Drive Hull To 4.2m (Selected Drive Rig)", true)]
        static bool FitDriveHullValidate() => ReplaceSteeringWheelValidate();

        [MenuItem("AAA Tools/Fit Rig To Hull (Selected)", false, 20)]
        static void FitRigToHull()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                FlightController flight = selected.GetComponent<FlightController>();
                if (flight != null)
                {
                    FlightRigBuilder.FitRigToHull(selected);
                }
            }
        }

        [MenuItem("AAA Tools/Fit Rig To Hull (Selected)", true)]
        static bool FitRigToHullValidate()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                if (selected.GetComponent<FlightController>() != null)
                {
                    return true;
                }
            }

            return false;
        }

        [MenuItem("AAA Tools/Flip Nose 180 (Selected)", false, 21)]
        static void FlipNose()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                FlightController flight = selected.GetComponent<FlightController>();
                if (flight != null)
                {
                    Undo.RecordObject(flight, "Flip Nose 180");
                    flight.FlipNose();
                    EditorUtility.SetDirty(flight);
                }

                DriveController drive = selected.GetComponent<DriveController>();
                if (drive != null)
                {
                    Undo.RegisterFullObjectHierarchyUndo(drive.gameObject, "Flip Nose 180");
                    Undo.RecordObject(drive, "Flip Nose 180");
                    drive.FlipNose();
                    drive.DeriveWheelAnchorsFromBounds();
                    EditorUtility.SetDirty(drive);
                }
            }
        }

        [MenuItem("AAA Tools/Flip Nose 180 (Selected)", true)]
        static bool FlipNoseValidate()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                if (selected.GetComponent<FlightController>() != null ||
                    selected.GetComponent<DriveController>() != null)
                {
                    return true;
                }
            }

            return false;
        }

        [MenuItem("AAA Tools/Validate assembled asset...", false, 100)]
        static void ValidateAsset()
        {
            string folder = EditorUtility.OpenFolderPanel("Select AAA asset slug folder", "Assets", "");
            if (string.IsNullOrEmpty(folder))
            {
                return;
            }

            string slug = Path.GetFileName(folder);
            string assetKind = InferKindFromPath(folder);
            var result = AssetAssemblyValidator.Validate(slug, assetKind);
            if (result.ok)
            {
                Debug.Log($"[{AaaLabels.ForKind(assetKind)}] Validation passed for {slug}.");
            }
            else
            {
                Debug.LogError($"[{AaaLabels.ForKind(assetKind)}] Validation failed for {slug}: {string.Join("; ", result.errors)}");
            }
        }

        static bool HasRendererSelection()
        {
            foreach (GameObject selected in Selection.gameObjects)
            {
                if (selected.GetComponentInChildren<Renderer>() != null)
                {
                    return true;
                }
            }

            return false;
        }

        static string InferKindFromPath(string folder)
        {
            string normalized = folder.Replace('\\', '/');
            if (normalized.Contains("/Aircraft/"))
            {
                return "aircraft";
            }

            if (normalized.Contains("/Vehicles/"))
            {
                return "vehicle";
            }

            return "character";
        }
    }
}
#endif
