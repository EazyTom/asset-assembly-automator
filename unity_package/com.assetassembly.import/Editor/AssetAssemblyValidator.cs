#if UNITY_EDITOR
using System;
using System.IO;
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
            if (!AssetDatabase.IsValidFolder(root.Replace("Assets/", "Assets/")))
            {
                errors.Add($"Missing asset root: {root}");
            }
            else
            {
                checks.Add("asset_root_exists");
            }

            var prefab = Directory.Exists(Path.Combine(Application.dataPath, "..", prefabDir))
                ? Directory.GetFiles(Path.Combine(Application.dataPath, "..", prefabDir), "*.prefab")
                : Array.Empty<string>();
            if (prefab.Length == 0)
                errors.Add("Prefab missing under Prefabs/");
            else
                checks.Add("prefab_present");

            if (assetKind == "character")
            {
                var meshPath = $"{root}/Source/Character_output.fbx";
                if (!File.Exists(ToAbsolute(meshPath)))
                    errors.Add("Character rig FBX missing");
                else
                    checks.Add("rig_fbx_present");
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

            result.checks = checks.ToArray();
            result.errors = errors.ToArray();
            result.ok = errors.Count == 0;
            return result;
        }

        [MenuItem("Tools/AAA/Validate assembled asset...")]
        public static void ValidateMenu()
        {
            var slug = EditorUtility.DisplayDialogComplex(
                "Validate",
                "Enter slug in console log after picking from Project window.",
                "OK",
                "Cancel",
                "") == 0
                ? Selection.activeObject != null ? Selection.activeObject.name : ""
                : "";
            if (string.IsNullOrWhiteSpace(slug))
            {
                Debug.LogWarning("[AAA] Select a prefab or enter slug manually.");
                return;
            }
            var result = Validate(slug, "character");
            Debug.Log(result.ok ? "[AAA] Validation passed" : "[AAA] Validation failed: " +
                string.Join("; ", result.errors));
        }

        static string ToAbsolute(string assetPath) =>
            Path.GetFullPath(Path.Combine(Application.dataPath, "..", assetPath));
    }
}
#endif
