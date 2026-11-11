#if UNITY_EDITOR
using System;
using System.IO;
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    public static class AssetAssemblyValidator
    {
        [Serializable]
        public class ValidationResult
        {
            public bool ok;
            public string[] checks = Array.Empty<string>();
            public string[] errors = Array.Empty<string>();
        }

        public static ValidationResult Validate(string slug, string assetKind)
        {
            var result = new ValidationResult();
            var checks = new System.Collections.Generic.List<string>();
            var errors = new System.Collections.Generic.List<string>();

            var folder = assetKind switch
            {
                "vehicle" => "Vehicles",
                "aircraft" => "Aircraft",
                _ => "Characters",
            };
            var root = $"Assets/{folder}/{slug}";
            var prefabDir = $"{root}/Prefabs";
            if (!Directory.Exists(ToAbsolute(root)))
            {
                errors.Add($"Missing asset root: {root}");
            }
            else
            {
                checks.Add("asset_root_exists");
            }

            string[] prefabFiles = Directory.Exists(ToAbsolute(prefabDir))
                ? Directory.GetFiles(ToAbsolute(prefabDir), "*.prefab")
                : Array.Empty<string>();
            GameObject prefabRoot = null;
            if (prefabFiles.Length == 0)
            {
                errors.Add("Prefab missing under Prefabs/");
            }
            else
            {
                checks.Add("prefab_present");
                prefabRoot = AssetDatabase.LoadAssetAtPath<GameObject>(
                    $"{prefabDir}/{Path.GetFileName(prefabFiles[0])}");
            }

            if (assetKind == "character")
            {
                var meshPath = $"{root}/Source/Character_output.fbx";
                if (!File.Exists(ToAbsolute(meshPath)))
                {
                    errors.Add("Character rig FBX missing");
                }
                else
                {
                    checks.Add("rig_fbx_present");
                }
            }
            else
            {
                var sourceDir = ToAbsolute($"{root}/Source");
                if (!Directory.Exists(sourceDir) || Directory.GetFiles(sourceDir, "*.fbx").Length == 0)
                {
                    errors.Add("Source FBX missing");
                }
                else
                {
                    checks.Add("source_fbx_present");
                }
            }

            var texDir = ToAbsolute($"{root}/Textures");
            if (Directory.Exists(texDir))
            {
                checks.Add("textures_folder");
                foreach (var name in Directory.GetFiles(texDir, "*.png"))
                {
                    var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(
                        $"{root}/Textures/{Path.GetFileName(name)}");
                    if (tex != null && tex.width >= 512)
                    {
                        checks.Add("base_texture_ok");
                        break;
                    }
                }
            }
            else
            {
                errors.Add("Textures folder missing");
            }

            if (prefabRoot != null)
            {
                ValidateController(prefabRoot, assetKind, checks, errors);
            }

            result.checks = checks.ToArray();
            result.errors = errors.ToArray();
            result.ok = errors.Count == 0;
            return result;
        }

        static void ValidateController(
            GameObject prefabRoot,
            string assetKind,
            System.Collections.Generic.List<string> checks,
            System.Collections.Generic.List<string> errors)
        {
            switch (assetKind)
            {
                case "aircraft":
                    if (prefabRoot.GetComponentInChildren<FlightController>() == null)
                    {
                        errors.Add($"{AaaLabels.Aircraft} requires FlightController on rig root");
                    }
                    else
                    {
                        checks.Add("flight_controller_present");
                    }

                    break;
                case "vehicle":
                    var drive = prefabRoot.GetComponentInChildren<DriveController>();
                    if (drive == null)
                    {
                        errors.Add($"{AaaLabels.Vehicle} requires DriveController on rig root");
                    }
                    else
                    {
                        checks.Add("drive_controller_present");
                        if (drive.FrontLeft.localPosition == Vector3.zero)
                        {
                            errors.Add("Wheel anchors not configured");
                        }
                        else
                        {
                            checks.Add("wheel_anchors_present");
                        }
                    }

                    break;
                default:
                    checks.Add("character_prefab");
                    break;
            }
        }

        static string ToAbsolute(string assetPath) =>
            Path.GetFullPath(Path.Combine(Application.dataPath, "..", assetPath));
    }
}
#endif
