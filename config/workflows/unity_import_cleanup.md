# Unity cleanup — {character_slug}

You are a Cursor agent with Unity MCP. **AAA default:** AnkleBreaker **`unity`** / **`user-unity`**. Unity 6 Editor must be open on `{unity_project_path}`. Use MCP tools only — no Python in this repo.

> **Fallbacks:** Coplay **`user-unityMCP`** — use `execute_code` + `read_console` with the same C# script below. Official **`user-unity-mcp`** — wrap the script in `Unity_RunCommand`. Prefer the tool named in appended Facts for the configured bridge.

## Goal

**Remove only the selected character `{character_slug}`** — nothing else under `Assets/Characters/`, no other `PF_*` scene objects.

Delete completely:

- **Entire folder** `Assets/Characters/{character_slug}/` (case-insensitive match on disk and in AssetDatabase)
- **Every scene instance** named `PF_{character_slug}` or `{character_slug}` (case-insensitive, any depth, active scene only)
- Prefab asset `Assets/Characters/{character_slug}/Prefabs/PF_{character_slug}.prefab` if still present
- Legacy patrol script and slug-matched Editor import utilities (see Facts)

**Do not delete** `DarkWireHumanoid`, `PF_DarkWireHumanoid`, or any character whose slug is not `{character_slug}`.

## Hard constraints

- **Do NOT** create or edit `.cs` files.
- **Do NOT** use `glob`, `grep`, or project exploration.
- Run **exactly one** code execution with the script below — slug `{character_slug}` is already substituted — then **one** console read.
  - **Default (AnkleBreaker):** `unity_execute_code` then `unity_console_log`
  - **Coplay:** `execute_code` then `read_console`
  - **Official:** `Unity_RunCommand` then `Unity_GetConsoleLogs`
- If the result is not `SUCCESS`, re-run the **same** script once. Do not use alternate approaches.

Cleanup **failed** unless the configured execute tool returns a line starting with `SUCCESS`.

---

## Execute script (slug = `{character_slug}` ONLY)

Run via configured MCP execute tool (default: **`unity_execute_code`**):

```csharp
#if UNITY_EDITOR
var slug = "{character_slug}";
var prefabName = "PF_" + slug;
var charFolder = "Assets/Characters/" + slug;
var prefabAsset = charFolder + "/Prefabs/PF_" + slug + ".prefab";
var patrolScript = "Assets/Scripts/" + slug + "CircularPatrol.cs";
var report = new System.Collections.Generic.List<string>();
var activeScene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
var projectRoot = System.IO.Path.GetFullPath(System.IO.Path.Combine(UnityEngine.Application.dataPath, ".."));

System.Func<string, bool> matchesCharacterObjectName = (name) => {
    if (string.IsNullOrEmpty(name)) return false;
    return string.Equals(name, prefabName, System.StringComparison.OrdinalIgnoreCase)
        || string.Equals(name, slug, System.StringComparison.OrdinalIgnoreCase);
};

System.Func<string, bool> deleteAssetPath = (path) => {
    if (string.IsNullOrEmpty(path)) return false;
    var rel = path.Replace('\\', '/');
    if (UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(rel) != null || UnityEditor.AssetDatabase.IsValidFolder(rel))
    {
        if (UnityEditor.AssetDatabase.DeleteAsset(rel))
        {
            report.Add("deleted asset: " + rel);
            return true;
        }
        report.Add("WARN AssetDatabase.DeleteAsset failed: " + rel);
    }
    var fullPath = System.IO.Path.GetFullPath(System.IO.Path.Combine(projectRoot, rel));
    if (System.IO.Directory.Exists(fullPath) || System.IO.File.Exists(fullPath))
    {
        UnityEditor.FileUtil.DeleteFileOrDirectory(rel);
        var meta = rel + ".meta";
        var metaFull = System.IO.Path.GetFullPath(System.IO.Path.Combine(projectRoot, meta));
        if (System.IO.File.Exists(metaFull)) UnityEditor.FileUtil.DeleteFileOrDirectory(meta);
        report.Add("deleted via FileUtil: " + rel);
        return true;
    }
    return false;
};

System.Func<System.Collections.Generic.List<string>> resolveCharacterFolderPaths = () => {
    var paths = new System.Collections.Generic.List<string>();
    if (!string.IsNullOrEmpty(charFolder)) paths.Add(charFolder);
    if (UnityEditor.AssetDatabase.IsValidFolder("Assets/Characters"))
    {
        foreach (var sub in UnityEditor.AssetDatabase.GetSubFolders("Assets/Characters"))
        {
            var folderName = System.IO.Path.GetFileName(sub.Replace('\\', '/'));
            if (string.Equals(folderName, slug, System.StringComparison.OrdinalIgnoreCase)
                && !paths.Contains(sub))
                paths.Add(sub);
        }
    }
    var diskChars = System.IO.Path.Combine(UnityEngine.Application.dataPath, "Characters");
    if (System.IO.Directory.Exists(diskChars))
    {
        foreach (var dir in System.IO.Directory.GetDirectories(diskChars))
        {
            var folderName = System.IO.Path.GetFileName(dir);
            if (!string.Equals(folderName, slug, System.StringComparison.OrdinalIgnoreCase)) continue;
            var assetPath = "Assets/Characters/" + folderName;
            if (!paths.Contains(assetPath)) paths.Add(assetPath);
        }
    }
    return paths;
};

System.Func<int> destroyMatchingSceneObjects = () => {
    var toDestroy = new System.Collections.Generic.List<UnityEngine.GameObject>();
    foreach (var go in UnityEngine.Resources.FindObjectsOfTypeAll<UnityEngine.GameObject>())
    {
        if (go == null) continue;
        if (UnityEditor.EditorUtility.IsPersistent(go)) continue;
        if (!go.scene.IsValid() || go.scene != activeScene) continue;
        if (!matchesCharacterObjectName(go.name)) continue;
        if (!toDestroy.Contains(go)) toDestroy.Add(go);
    }
    var count = 0;
    foreach (var go in toDestroy)
    {
        if (go == null) continue;
        report.Add("destroyed scene object: " + go.name);
        UnityEngine.Object.DestroyImmediate(go);
        count++;
    }
    return count;
};

System.Func<bool> characterFolderStillExists = () => {
    foreach (var path in resolveCharacterFolderPaths())
    {
        if (UnityEditor.AssetDatabase.IsValidFolder(path)) return true;
        var rel = path.Replace('\\', '/');
        var fullPath = System.IO.Path.GetFullPath(System.IO.Path.Combine(projectRoot, rel));
        if (System.IO.Directory.Exists(fullPath)) return true;
    }
    return false;
};

System.Func<int> countMatchingSceneObjects = () => {
    var count = 0;
    foreach (var go in UnityEngine.Resources.FindObjectsOfTypeAll<UnityEngine.GameObject>())
    {
        if (go == null) continue;
        if (UnityEditor.EditorUtility.IsPersistent(go)) continue;
        if (!go.scene.IsValid() || go.scene != activeScene) continue;
        if (matchesCharacterObjectName(go.name)) count++;
    }
    return count;
};

System.Action runCleanupPass = () => {
    var destroyed = destroyMatchingSceneObjects();
    if (destroyed == 0) report.Add("no scene instance matched: " + prefabName + " or " + slug);

    if (UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(prefabAsset) != null
        || System.IO.File.Exists(System.IO.Path.Combine(projectRoot, prefabAsset.Replace('/', System.IO.Path.DirectorySeparatorChar))))
        deleteAssetPath(prefabAsset);

    var deletedAnyFolder = false;
    foreach (var folderPath in resolveCharacterFolderPaths())
        deletedAnyFolder = deleteAssetPath(folderPath) || deletedAnyFolder;
    if (!deletedAnyFolder) report.Add("character folder not found: " + charFolder);

    if (UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(patrolScript) != null)
        deleteAssetPath(patrolScript);

    System.Action<string> deleteSlugScriptsInFolder = (folder) => {
        if (!UnityEditor.AssetDatabase.IsValidFolder(folder)) return;
        foreach (var guid in UnityEditor.AssetDatabase.FindAssets("t:Script", new string[] { folder }))
        {
            var path = UnityEditor.AssetDatabase.GUIDToAssetPath(guid);
            var fileName = System.IO.Path.GetFileNameWithoutExtension(path);
            if (fileName.IndexOf(slug, System.StringComparison.OrdinalIgnoreCase) < 0) continue;
            if (fileName.EndsWith("ImportUtility", System.StringComparison.OrdinalIgnoreCase)
                || fileName.EndsWith("CircularPatrol", System.StringComparison.OrdinalIgnoreCase))
                deleteAssetPath(path);
        }
    };
    deleteSlugScriptsInFolder("Assets/Scripts");
    deleteSlugScriptsInFolder("Assets/Editor");

    UnityEditor.AssetDatabase.Refresh(UnityEditor.ImportAssetOptions.ForceUpdate);
    UnityEditor.AssetDatabase.SaveAssets();
    UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(activeScene);
    UnityEditor.SceneManagement.EditorSceneManager.SaveOpenScenes();
};

runCleanupPass();

var remainingScene = countMatchingSceneObjects();
if (remainingScene > 0 || characterFolderStillExists())
{
    report.Add("retry cleanup pass");
    runCleanupPass();
    remainingScene = countMatchingSceneObjects();
}

if (remainingScene > 0)
    return "ERROR scene instances remain for slug " + slug + ": " + remainingScene + "\n" + string.Join("\n", report.ToArray());
if (characterFolderStillExists())
    return "ERROR character folder still exists for slug " + slug + " under Assets/Characters\n" + string.Join("\n", report.ToArray());

return "SUCCESS removed character slug=" + slug + "\n" + string.Join("\n", report.ToArray());
#endif
```

## Validation (must pass)

`SUCCESS` means:

- Zero scene objects named `PF_{character_slug}` or `{character_slug}` in the active scene
- No folder under `Assets/Characters/` whose name matches `{character_slug}` (case-insensitive), on disk or in AssetDatabase

Report the configured execute tool return value verbatim.

## Do not delete

- Other slugs under `Assets/Characters/` (e.g. `DarkWireHumanoid`, `leon`, `chr_*` unless that is the selected slug)
- `PF_DarkWireHumanoid` or any `PF_*` that does not match `{character_slug}`
- Terrain, lighting, cameras
