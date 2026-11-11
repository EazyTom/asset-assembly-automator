#if UNITY_EDITOR
using System.IO;
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    public static class AircraftManifestImportUtility
    {
        public static bool ImportFromSlug(string slug, float targetSizeMeters = 6f)
        {
            var root = $"Assets/Aircraft/{slug}";
            var meshPath = FindMeshFbx(root);
            if (string.IsNullOrEmpty(meshPath))
            {
                Debug.LogError($"[{AaaLabels.Aircraft}] FBX missing under Source/");
                return false;
            }

            MeshyHdImportUtility.PrepareFbx(meshPath, targetSizeMeters);
            var prefabPath = $"{root}/Prefabs/PF_{slug}.prefab";
            EnsureFolder(prefabPath);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(meshPath);
            if (model == null)
            {
                return false;
            }

            var instance = (GameObject)PrefabUtility.InstantiatePrefab(model);
            instance.name = $"PF_{slug}";
            GameObject rig = FlightRigBuilder.Build(instance, targetSizeMeters);
            PrefabUtility.SaveAsPrefabAsset(rig, prefabPath, out bool ok);
            Object.DestroyImmediate(rig);
            return ok;
        }

        static string FindMeshFbx(string root)
        {
            var source = Path.Combine(Application.dataPath, "..", root, "Source");
            if (!Directory.Exists(source))
            {
                return null;
            }

            foreach (var file in Directory.GetFiles(source, "*.fbx"))
            {
                return $"{root}/Source/{Path.GetFileName(file)}";
            }

            return null;
        }

        static void EnsureFolder(string assetPath)
        {
            var dir = Path.GetDirectoryName(Path.Combine(Application.dataPath, "..", assetPath));
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }
        }
    }
}
#endif
