#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    public static class MeshyHdImportUtility
    {
        static readonly int BaseMapId = Shader.PropertyToID("_BaseMap");
        static readonly int BumpMapId = Shader.PropertyToID("_BumpMap");
        static readonly int MetallicGlossMapId = Shader.PropertyToID("_MetallicGlossMap");

        // meshy_* hints are DCC-bridge naming compatibility — do not remove.
        static readonly string[] MaterialSlotCandidates = { "Material.001", "Material", "Image_0", "base_color" };

        public static Material PrepareFbx(string fbxAssetPath, float targetSizeMeters = 0f)
        {
            if (targetSizeMeters > 0f)
            {
                FitImportedAssetToWorld(fbxAssetPath, targetSizeMeters);
            }

            var folder = Path.GetDirectoryName(fbxAssetPath)?.Replace('\\', '/');
            if (string.IsNullOrEmpty(folder))
            {
                return null;
            }

            var material = BuildOrUpdateMaterial(folder);
            if (material == null)
            {
                return null;
            }

            var importer = AssetImporter.GetAtPath(fbxAssetPath) as ModelImporter;
            if (importer == null)
            {
                return material;
            }

            importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
            importer.materialLocation = ModelImporterMaterialLocation.External;
            RemapMaterialSlots(importer, material);
            importer.SaveAndReimport();
            return material;
        }

        public static void FitImportedAssetToWorld(string fbxAssetPath, float targetSizeMeters)
        {
            var importer = AssetImporter.GetAtPath(fbxAssetPath) as ModelImporter;
            if (importer == null || targetSizeMeters <= 0f)
            {
                return;
            }

            var temp = AssetDatabase.LoadAssetAtPath<GameObject>(fbxAssetPath);
            if (temp == null)
            {
                return;
            }

            float current = HullUtility.MeasureLongestAxis(temp);
            if (current < 0.001f)
            {
                return;
            }

            float factor = targetSizeMeters / current;
            if (Mathf.Abs(factor - 1f) < 0.01f)
            {
                return;
            }

            importer.globalScale = importer.globalScale * factor;
            importer.SaveAndReimport();
            Debug.Log($"[AAA] Scaled {fbxAssetPath} by {factor:F3} to target {targetSizeMeters:F1}m (measured {current:F2}m).");
        }

        static void RemapMaterialSlots(ModelImporter importer, Material material)
        {
            foreach (string slot in MaterialSlotCandidates)
            {
                importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), slot), material);
            }
        }

        public static Material BuildOrUpdateMaterial(string folder)
        {
            var baseColor = FindTexture(folder, "base_color", "BaseColor", "meshy_basecolor");
            if (baseColor == null)
            {
                return null;
            }

            EnsureHdTextureImport(AssetDatabase.GetAssetPath(baseColor));
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var matPath = $"{folder}/Materials/MAT_Body.mat";
            EnsureFolder(matPath);
            var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
            if (mat == null)
            {
                mat = new Material(shader) { name = "MAT_Body" };
                AssetDatabase.CreateAsset(mat, matPath);
            }

            mat.shader = shader;
            mat.SetTexture(BaseMapId, baseColor);
            var normal = FindTexture(folder, "normal", "meshy_normal");
            if (normal != null)
            {
                EnsureHdTextureImport(AssetDatabase.GetAssetPath(normal), normal: true);
                mat.SetTexture(BumpMapId, normal);
            }

            var metallic = FindTexture(folder, "metallic", "roughness", "meshy_metallic");
            if (metallic != null)
            {
                EnsureHdTextureImport(AssetDatabase.GetAssetPath(metallic));
                mat.SetTexture(MetallicGlossMapId, metallic);
            }

            EditorUtility.SetDirty(mat);
            return mat;
        }

        static Texture2D FindTexture(string folder, params string[] hints)
        {
            var texFolder = folder + "/Textures";
            if (!Directory.Exists(Path.Combine(Application.dataPath, "..", texFolder)))
            {
                texFolder = folder;
            }

            var abs = Path.Combine(Application.dataPath, "..", texFolder);
            if (!Directory.Exists(abs))
            {
                return null;
            }

            foreach (var file in Directory.GetFiles(abs, "*.png"))
            {
                var lower = Path.GetFileName(file).ToLowerInvariant();
                foreach (var hint in hints)
                {
                    if (lower.Contains(hint))
                    {
                        return AssetDatabase.LoadAssetAtPath<Texture2D>($"{texFolder}/{Path.GetFileName(file)}");
                    }
                }
            }

            return null;
        }

        public static void EnsureHdTextureImport(string assetPath, bool normal = false)
        {
            var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
            if (importer == null)
            {
                return;
            }

            importer.maxTextureSize = 8192;
            importer.textureCompression = TextureImporterCompression.CompressedHQ;
            if (normal)
            {
                importer.textureType = TextureImporterType.NormalMap;
            }

            importer.SaveAndReimport();
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
