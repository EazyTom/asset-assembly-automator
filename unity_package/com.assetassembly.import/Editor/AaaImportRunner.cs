#if UNITY_EDITOR
using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    [InitializeOnLoad]
    public static class AaaImportRunner
    {
        static AaaImportRunner()
        {
            EditorApplication.update += Tick;
        }

        static void Tick()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating)
                return;

            foreach (var kindFolder in new[] { "Characters", "Vehicles", "Aircraft" })
            {
                var root = Path.Combine(Application.dataPath, kindFolder);
                if (!Directory.Exists(root))
                    continue;
                foreach (var slugDir in Directory.GetDirectories(root))
                {
                    TryProcessSlug(slugDir, kindFolder);
                }
            }
        }

        static void TryProcessSlug(string slugDir, string kindFolder)
        {
            var requestPath = Path.Combine(slugDir, ".aaa", "import_request.json");
            if (!File.Exists(requestPath))
                return;

            var slug = Path.GetFileName(slugDir);
            var assetKind = kindFolder switch
            {
                "Vehicles" => "vehicle",
                "Aircraft" => "aircraft",
                _ => "character",
            };

            var started = DateTime.UtcNow;
            var ok = false;
            var errors = new System.Collections.Generic.List<string>();

            try
            {
                ok = assetKind switch
                {
                    "vehicle" => VehicleManifestImportUtility.ImportFromSlug(slug),
                    "aircraft" => AircraftManifestImportUtility.ImportFromSlug(slug),
                    _ => CharacterManifestImportUtility.ImportFromSlug(slug),
                };
                if (!ok)
                    errors.Add("ImportFromSlug returned false");
            }
            catch (Exception ex)
            {
                errors.Add(ex.Message);
            }

            var validation = AssetAssemblyValidator.Validate(slug, assetKind);
            ok = ok && validation.ok;
            if (validation.errors != null)
                errors.AddRange(validation.errors);

            var durationMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
            WriteResult(slugDir, ok, errors, durationMs, validation.checks);
            File.Delete(requestPath);
        }

        static void WriteResult(
            string slugDir,
            bool ok,
            System.Collections.Generic.List<string> errors,
            int durationMs,
            string[] checks)
        {
            var aaaDir = Path.Combine(slugDir, ".aaa");
            Directory.CreateDirectory(aaaDir);
            var json = JsonUtility.ToJson(new ResultPayload
            {
                ok = ok,
                duration_ms = durationMs,
                checks = checks ?? Array.Empty<string>(),
                errors = errors?.ToArray() ?? Array.Empty<string>(),
            }, true);
            File.WriteAllText(Path.Combine(aaaDir, "unity_import_result.json"), json);
        }

        [Serializable]
        class ResultPayload
        {
            public bool ok;
            public int duration_ms;
            public string[] checks;
            public string[] errors;
        }
    }
}
#endif
