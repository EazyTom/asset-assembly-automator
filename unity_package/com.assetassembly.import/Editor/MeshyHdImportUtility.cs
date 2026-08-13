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

        public static Material PrepareFbx(string fbxAssetPath)
        {
            var folder = Path.GetDirectoryName(fbxAssetPath)?.Replace('\\', '/');
            if (string.IsNullOrEmpty(folder))
                return null;

            var material = BuildOrUpdateMaterial(folder);
            if (material == null)
                return null;

            var importer = AssetImporter.GetAtPath(fbxAssetPath) as ModelImporter;
            if (importer == null)
                return material;

            importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
            importer.materialLocation = ModelImporterMaterialLocation.External;
            importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "Material.001"), material);
            importer.SaveAndReimport();
            return material;
        }

        public static Material BuildOrUpdateMaterial(string folder)
        {
            var baseColor = FindTexture(folder, "base_color", "BaseColor", "meshy_basecolor");
            if (baseColor == null)
                return null;

            EnsureHdTextureImport(baseColor);
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
                EnsureHdTextureImport(normal, normal: true);
                mat.SetTexture(BumpMapId, normal);
            }
            var metallic = FindTexture(folder, "metallic", "roughness", "meshy_metallic");
            if (metallic != null)
            {
                EnsureHdTextureImport(metallic);
                mat.SetTexture(MetallicGlossMapId, metallic);
            }
            EditorUtility.SetDirty(mat);
            return mat;
        }

        static Texture2D FindTexture(string folder, params string[] hints)
        {
            var texFolder = folder + "/Textures";
            if (!Directory.Exists(Path.Combine(Application.dataPath, "..", texFolder)))
                texFolder = folder;
            var abs = Path.Combine(Application.dataPath, "..", texFolder);
            if (!Directory.Exists(abs))
                return null;
            foreach (var file in Directory.GetFiles(abs, "*.png"))
            {
                var lower = Path.GetFileName(file).ToLowerInvariant();
                foreach (var hint in hints)
                {
                    if (lower.Contains(hint))
                        return AssetDatabase.LoadAssetAtPath<Texture2D>($"{texFolder}/{Path.GetFileName(file)}");
                }
            }
            return null;
        }

        public static void EnsureHdTextureImport(string assetPath, bool normal = false)
        {
            var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
            if (importer == null)
                return;
            importer.maxTextureSize = 8192;
            importer.textureCompression = TextureImporterCompression.CompressedHQ;
            if (normal)
                importer.textureType = TextureImporterType.NormalMap;
            importer.SaveAndReimport();
        }

        static void EnsureFolder(string assetPath)
        {
            var dir = Path.GetDirectoryName(Path.Combine(Application.dataPath, "..", assetPath));
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
        }
    }
}
#endif
