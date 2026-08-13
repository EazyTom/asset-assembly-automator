#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
/// <summary>
/// Manifest-driven Meshy character import: humanoid rig, clips, animator, material, prefab, scene placement.
/// </summary>
public static class CharacterManifestImportUtility
{
    private static readonly (string hint, string stateName)[] IdleSpecs =
    {
        ("idle12", "Idle12"),
        ("idle4", "Idle4"),
        ("idle3", "Idle3"),
    };

    [Serializable]
    private class ImportManifest
    {
        public int pipeline_id;
        public string asset_name;
        public RigConfig rig_config;
        public AnimatorConfig animator;
        public SceneConfig scene;
    }

    [Serializable]
    private class RigConfig
    {
        public string animationType;
        public string avatarSetup;
        public float globalScale = 0.01f;
    }

    [Serializable]
    private class AnimatorConfig
    {
        public string controller;
        public string default_state;
        public string[] idle_clips;
        public string[] locomotion_clips;
        public bool extract_clips_to_anim = true;
        public bool apply_root_motion;
    }

    [Serializable]
    private class SceneConfig
    {
        public string prefab_name;
        public string scale_reference;
        public int default_animator_gait;
        public int default_idle_index;
        public string patrol;
        public bool no_scripts = true;
    }

    [MenuItem("Tools/Characters/Import character from manifest...")]
    public static void ImportFromManifestMenu() => SlugImportWindow.ShowWindow();

    public static bool ImportFromSlug(string slug)
    {
        if (string.IsNullOrWhiteSpace(slug))
        {
            Debug.LogError("[Import] Character slug is required.");
            return false;
        }

        slug = slug.Trim();
        var root = "Assets/Characters/" + slug;
        var manifestPath = root + "/unity_import_manifest.json";
        if (!File.Exists(ToAbsolute(manifestPath)))
        {
            Debug.LogError("[Import] Manifest not found: " + manifestPath);
            return false;
        }

        ImportManifest manifest;
        try
        {
            manifest = JsonUtility.FromJson<ImportManifest>(File.ReadAllText(manifestPath));
        }
        catch (Exception ex)
        {
            Debug.LogError("[Import] Failed to parse manifest: " + ex.Message);
            return false;
        }

        if (manifest == null)
        {
            Debug.LogError("[Import] Manifest deserialized to null: " + manifestPath);
            return false;
        }

        if (manifest.animator == null || manifest.scene == null)
        {
            Debug.LogError("[Import] Manifest missing animator or scene section for " + slug);
            return false;
        }

        return ImportCharacter(root, slug, manifest);
    }

    private static bool ImportCharacter(string root, string slug, ImportManifest manifest)
    {
        var meshPath = root + "/Source/Character_output.fbx";
        if (!File.Exists(ToAbsolute(meshPath)))
        {
            Debug.LogError("[Import] Rig FBX missing: " + meshPath);
            return false;
        }

        var walkPath = FindLocomotionFbx(root, "walk");
        var runPath = FindLocomotionFbx(root, "run");
        var texPath = FindBaseColorTexture(root);
        var animFolder = root + "/Animations";
        var matPath = root + "/Materials/MAT_" + slug + "_Body.mat";
        var controllerPath = root + "/" + manifest.animator.controller;
        var prefabPath = root + "/Prefabs/" + manifest.scene.prefab_name + ".prefab";

        EnsureAssetFolders(animFolder, matPath, controllerPath, prefabPath);

        var scale = manifest.rig_config != null ? manifest.rig_config.globalScale : 0.01f;

        if (!ConfigureMeshImporter(meshPath, scale))
        {
            Debug.LogError("[Import] Mesh importer configuration failed: " + meshPath);
            return false;
        }

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        var avatar = AssetDatabase.LoadAssetAtPath<Avatar>(meshPath);
        if (avatar == null)
        {
            Debug.LogError("[Import] Humanoid avatar not created for: " + meshPath);
            return false;
        }

        if (!string.IsNullOrEmpty(walkPath))
            ConfigureAnimationImporter(walkPath, scale, avatar, "walk");
        if (!string.IsNullOrEmpty(runPath))
            ConfigureAnimationImporter(runPath, scale, avatar, "run");

        var idleFbxPaths = new Dictionary<string, string>();
        foreach (var (hint, stateName) in IdleSpecs)
        {
            var fbx = FindAnimationFbx(root, hint);
            if (string.IsNullOrEmpty(fbx))
            {
                Debug.LogWarning("[Import] Idle FBX not found for " + stateName + " (hint: " + hint + ")");
                continue;
            }

            idleFbxPaths[stateName] = fbx;
            ConfigureAnimationImporter(fbx, scale, avatar, hint, "idle");
        }

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        AnimationClip idle3Clip = null;
        AnimationClip idle4Clip = null;
        AnimationClip idle12Clip = null;
        AnimationClip walkClip = null;
        AnimationClip runClip = null;

        if (manifest.animator.extract_clips_to_anim)
        {
            foreach (var (hint, stateName) in IdleSpecs)
            {
                if (!idleFbxPaths.TryGetValue(stateName, out var fbx))
                    continue;

                var clip = ExtractClip(fbx, new[] { hint, "idle" }, slug + "_" + stateName, animFolder);
                switch (stateName)
                {
                    case "Idle3": idle3Clip = clip; break;
                    case "Idle4": idle4Clip = clip; break;
                    case "Idle12": idle12Clip = clip; break;
                }
            }

            if (!string.IsNullOrEmpty(walkPath))
                walkClip = ExtractClip(walkPath, new[] { "walk" }, slug + "_Walk", animFolder);
            if (!string.IsNullOrEmpty(runPath))
                runClip = ExtractClip(runPath, new[] { "run" }, slug + "_Run", animFolder);
        }

        if (walkClip == null || walkClip.length < 0.02f)
            Debug.LogWarning("[Import] Walk clip missing or zero-length — check avatar copy from rig.");

        var material = CreateMaterial(matPath, texPath);
        if (material == null && !string.IsNullOrEmpty(meshPath))
            MeshyHdImportUtility.PrepareFbx(meshPath);
        else
            AssignMaterial(material, meshPath);

        var modelPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(meshPath);
        if (modelPrefab == null)
        {
            Debug.LogError("[Import] Mesh FBX failed to load after import: " + meshPath);
            return false;
        }

        var instance = (GameObject)PrefabUtility.InstantiatePrefab(modelPrefab);
        instance.name = manifest.scene.prefab_name;

        ApplyScale(instance, manifest.scene.scale_reference);

        var animator = instance.GetComponent<Animator>() ?? instance.AddComponent<Animator>();
        animator.applyRootMotion = manifest.animator.apply_root_motion;
        animator.avatar = avatar;

        var controller = BuildCharacterController(
            controllerPath,
            idle3Clip,
            idle4Clip,
            idle12Clip,
            walkClip,
            runClip,
            manifest.animator.default_state);
        if (controller != null)
            animator.runtimeAnimatorController = controller;

        if (!manifest.scene.no_scripts && !string.IsNullOrEmpty(manifest.scene.patrol))
        {
            if (instance.GetComponent<AssetAssembly.Import.Runtime.CharacterOvalPatrol>() == null)
                instance.AddComponent<AssetAssembly.Import.Runtime.CharacterOvalPatrol>();
        }

        PrefabUtility.SaveAsPrefabAsset(instance, prefabPath, out bool prefabOk);
        UnityEngine.Object.DestroyImmediate(instance);

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        if (!prefabOk)
        {
            Debug.LogError("[Import] Prefab save failed: " + prefabPath);
            return false;
        }

        Debug.Log("[Import] Prefab saved: " + prefabPath);
        return PlaceInScene(prefabPath, manifest);
    }

    private static bool PlaceInScene(string prefabPath, ImportManifest manifest)
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
        {
            Debug.LogError("[Import] Cannot place — prefab missing: " + prefabPath);
            return false;
        }

        var existing = GameObject.Find(manifest.scene.prefab_name);
        if (existing != null)
            UnityEngine.Object.DestroyImmediate(existing);

        var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        instance.name = manifest.scene.prefab_name;

        var terrain = Terrain.activeTerrain ?? UnityEngine.Object.FindFirstObjectByType<Terrain>();
        var position = Vector3.zero;
        if (terrain != null)
        {
            var size = terrain.terrainData.size;
            position = terrain.transform.position + new Vector3(size.x * 0.5f, 0f, size.z * 0.5f);
            position.y = terrain.SampleHeight(position) + 0.05f;
        }

        instance.transform.position = position;

        var animator = instance.GetComponent<Animator>();
        if (animator != null)
        {
            animator.SetInteger("Gait", ResolveDefaultGait(manifest));
            animator.SetInteger("IdleIndex", ResolveDefaultIdleIndex(manifest));
        }

        Undo.RegisterCreatedObjectUndo(instance, "Place " + manifest.scene.prefab_name);
        Debug.Log("[Import] Placed " + manifest.scene.prefab_name + " at " + position);
        return true;
    }

    private static void EnsureAssetFolders(params string[] assetPaths)
    {
        foreach (var assetPath in assetPaths)
        {
            var dir = Path.GetDirectoryName(ToAbsolute(assetPath));
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
        }
    }

    private static bool ConfigureMeshImporter(string path, float globalScale)
    {
        var importer = GetModelImporter(path);
        if (importer == null)
            return false;

        importer.globalScale = globalScale;
        importer.materialImportMode = ModelImporterMaterialImportMode.None;
        importer.animationType = ModelImporterAnimationType.Human;
        importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
        importer.importAnimation = true;
        SetLoopOnMatchingClips(importer, "clip0", "idle");
        importer.SaveAndReimport();
        return true;
    }

    private static void ConfigureAnimationImporter(
        string path,
        float globalScale,
        Avatar sourceAvatar,
        params string[] loopHints)
    {
        if (sourceAvatar == null)
        {
            Debug.LogWarning("[Import] Skipping animation import (no source avatar): " + path);
            return;
        }

        var importer = GetModelImporter(path);
        if (importer == null)
            return;

        importer.globalScale = globalScale;
        importer.materialImportMode = ModelImporterMaterialImportMode.None;
        importer.animationType = ModelImporterAnimationType.Human;
        importer.importAnimation = true;
        importer.avatarSetup = ModelImporterAvatarSetup.CopyFromOther;
        importer.sourceAvatar = sourceAvatar;
        SetLoopOnMatchingClips(importer, loopHints);
        importer.SaveAndReimport();
    }

    private static ModelImporter GetModelImporter(string path)
    {
        if (!File.Exists(ToAbsolute(path)))
            return null;

        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
        return AssetImporter.GetAtPath(path) as ModelImporter;
    }

    private static void SetLoopOnMatchingClips(ModelImporter importer, params string[] hints)
    {
        var clips = importer.clipAnimations;
        if (clips == null || clips.Length == 0)
            clips = importer.defaultClipAnimations;

        if (clips == null || clips.Length == 0)
            return;

        foreach (var clip in clips)
        {
            var lower = clip.name.ToLowerInvariant();
            if (hints.Any(lower.Contains))
                clip.loopTime = true;
        }

        importer.clipAnimations = clips;
    }

    private static AnimationClip ExtractClip(
        string fbxPath,
        string[] hints,
        string assetName,
        string animFolder)
    {
        if (!File.Exists(ToAbsolute(fbxPath)))
            return null;

        var source = AssetDatabase.LoadAllAssetsAtPath(fbxPath)
            .OfType<AnimationClip>()
            .FirstOrDefault(c => !c.name.StartsWith("__") &&
                                 hints.Any(h => c.name.ToLowerInvariant().Contains(h)));

        if (source == null)
        {
            Debug.LogWarning("[Import] No clip in " + fbxPath + " for " + assetName);
            return null;
        }

        var assetPath = animFolder + "/" + assetName + ".anim";
        var existing = AssetDatabase.LoadAssetAtPath<AnimationClip>(assetPath);
        if (existing != null)
            AssetDatabase.DeleteAsset(assetPath);

        var copy = UnityEngine.Object.Instantiate(source);
        copy.name = assetName;
        AssetDatabase.CreateAsset(copy, assetPath);
        return copy;
    }

    private static Material CreateMaterial(string matPath, string texPath)
    {
        var shader = FindLitShader();
        var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
        if (mat == null)
        {
            mat = new Material(shader);
            AssetDatabase.CreateAsset(mat, matPath);
        }
        else
        {
            mat.shader = shader;
        }

        var tex = string.IsNullOrEmpty(texPath)
            ? null
            : AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
        if (tex != null)
            ApplyBaseColorTexture(mat, tex);

        EditorUtility.SetDirty(mat);
        return mat;
    }

    private static Shader FindLitShader()
    {
        string[] candidates =
        {
            "HDRP/Lit",
            "High Definition Render Pipeline/Lit",
            "Universal Render Pipeline/Lit",
            "URP/Lit",
            "Standard",
        };

        foreach (var name in candidates)
        {
            var shader = Shader.Find(name);
            if (shader != null)
                return shader;
        }

        return Shader.Find("Standard");
    }

    private static void ApplyBaseColorTexture(Material mat, Texture2D tex)
    {
        if (mat == null || tex == null)
            return;

        var shaderName = mat.shader != null ? mat.shader.name : string.Empty;
        if (shaderName.Contains("HDRP") || shaderName.Contains("High Definition"))
            mat.SetTexture("_BaseColorMap", tex);
        else if (shaderName.Contains("Universal") || shaderName.Contains("URP"))
            mat.SetTexture("_BaseMap", tex);
        else
            mat.SetTexture("_MainTex", tex);
    }

    private static void AssignMaterial(Material material, string meshPath)
    {
        foreach (var renderer in AssetDatabase.LoadAllAssetsAtPath(meshPath).OfType<Renderer>())
        {
            var mats = renderer.sharedMaterials;
            for (int i = 0; i < mats.Length; i++)
                mats[i] = material;
            renderer.sharedMaterials = mats;
            EditorUtility.SetDirty(renderer);
        }
    }

    private static void ApplyScale(GameObject instance, string scaleReference)
    {
        if (!string.IsNullOrEmpty(scaleReference))
        {
            var refName = scaleReference.Split(' ')[0];
            var reference = GameObject.Find(refName);
            if (reference != null)
            {
                var refHeight = GetRendererHeight(reference);
                var selfHeight = GetRendererHeight(instance);
                if (refHeight > 0.01f && selfHeight > 0.0001f)
                {
                    instance.transform.localScale = Vector3.one * (refHeight / selfHeight);
                    return;
                }

                instance.transform.localScale = reference.transform.localScale;
                return;
            }
        }

        var height = GetRendererHeight(instance);
        if (height > 0.01f)
        {
            const float targetHeight = 1.9f;
            instance.transform.localScale = Vector3.one * (targetHeight / height);
        }
    }

    private static float GetRendererHeight(GameObject go)
    {
        var renderers = go.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        if (renderers.Length == 0)
            return 0f;

        var bounds = renderers[0].bounds;
        for (int i = 1; i < renderers.Length; i++)
            bounds.Encapsulate(renderers[i].bounds);
        return bounds.size.y;
    }

    private static int ResolveDefaultGait(ImportManifest manifest) =>
        manifest.scene.default_animator_gait >= 0
            ? manifest.scene.default_animator_gait
            : manifest.animator.default_state switch
            {
                "Walk" => 1,
                "Run" => 2,
                _ => 0,
            };

    private static int ResolveDefaultIdleIndex(ImportManifest manifest) =>
        manifest.scene.default_idle_index >= 0 ? manifest.scene.default_idle_index : 0;

    private static string FindAnimationFbx(string characterRoot, string hint)
    {
        foreach (var folder in new[] { characterRoot + "/Animations", characterRoot + "/Source" })
        {
            var abs = ToAbsolute(folder);
            if (!Directory.Exists(abs))
                continue;

            foreach (var file in Directory.GetFiles(abs, "*.fbx", SearchOption.TopDirectoryOnly))
            {
                var name = Path.GetFileName(file).ToLowerInvariant();
                if (name.Contains(hint))
                    return folder + "/" + Path.GetFileName(file);
            }
        }

        return null;
    }

    private static string FindLocomotionFbx(string characterRoot, string kind)
    {
        var defaults = kind == "walk"
            ? new[] { "Animation_Walking_withSkin.fbx", "Animation_Walk_withSkin.fbx" }
            : new[] { "Animation_Running_withSkin.fbx", "Animation_Run_withSkin.fbx" };

        foreach (var fileName in defaults)
        {
            var path = characterRoot + "/Source/" + fileName;
            if (File.Exists(ToAbsolute(path)))
                return path;
        }

        return FindAnimationFbx(characterRoot, kind);
    }

    private static string FindBaseColorTexture(string characterRoot)
    {
        var texFolder = ToAbsolute(characterRoot + "/Textures");
        if (!Directory.Exists(texFolder))
            return null;

        var preferred = new[] { "base_color.png", "BaseColor.png", "basecolor.png", "albedo.png" };
        foreach (var name in preferred)
        {
            var path = characterRoot + "/Textures/" + name;
            if (File.Exists(ToAbsolute(path)))
                return path;
        }

        var firstPng = Directory.GetFiles(texFolder, "*.png", SearchOption.TopDirectoryOnly)
            .FirstOrDefault();
        return firstPng != null
            ? characterRoot + "/Textures/" + Path.GetFileName(firstPng)
            : null;
    }

    private static AnimatorController BuildCharacterController(
        string controllerPath,
        AnimationClip idle3Clip,
        AnimationClip idle4Clip,
        AnimationClip idle12Clip,
        AnimationClip walkClip,
        AnimationClip runClip,
        string defaultState = null)
    {
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
        if (controller == null)
            controller = AnimatorController.CreateAnimatorControllerAtPath(controllerPath);

        controller.parameters = new[]
        {
            new AnimatorControllerParameter
            {
                name = "Gait",
                type = AnimatorControllerParameterType.Int,
                defaultInt = 0,
            },
            new AnimatorControllerParameter
            {
                name = "IdleIndex",
                type = AnimatorControllerParameterType.Int,
                defaultInt = 0,
            },
        };

        var root = controller.layers[0].stateMachine;
        foreach (var transition in root.anyStateTransitions.ToList())
            root.RemoveAnyStateTransition(transition);
        foreach (var child in root.states.ToList())
            root.RemoveState(child.state);

        var idle3 = AddState(root, "Idle3", idle3Clip ?? walkClip);
        var idle4 = AddState(root, "Idle4", idle4Clip ?? walkClip);
        var idle12 = AddState(root, "Idle12", idle12Clip ?? walkClip);
        if (!HasAnimationData(idle3Clip) && walkClip != null)
            idle3.speed = 0f;
        if (!HasAnimationData(idle4Clip) && walkClip != null)
            idle4.speed = 0f;
        if (!HasAnimationData(idle12Clip) && walkClip != null)
            idle12.speed = 0f;

        var walk = AddState(root, "Walk", walkClip);
        var run = AddState(root, "Run", runClip);
        root.defaultState = defaultState switch
        {
            "Idle4" => idle4,
            "Idle12" => idle12,
            "Walk" => walk,
            "Run" => run,
            _ => idle3,
        };

        foreach (var idleState in new[] { idle3, idle4, idle12 })
            AddIdleTransitions(idleState);

        AddGaitTransition(idle3, walk, 1);
        AddGaitTransition(idle4, walk, 1);
        AddGaitTransition(idle12, walk, 1);
        AddGaitTransition(walk, idle3, 0);
        AddGaitTransition(run, idle3, 0);
        AddGaitTransition(walk, run, 2);
        AddGaitTransition(run, walk, 1);

        EditorUtility.SetDirty(controller);
        return controller;
    }

    private static void AddIdleTransitions(AnimatorState from)
    {
        var root = from.stateMachine;
        AnimatorState idle3 = null;
        AnimatorState idle4 = null;
        AnimatorState idle12 = null;
        foreach (var child in root.states)
        {
            if (child.state.name == "Idle3") idle3 = child.state;
            if (child.state.name == "Idle4") idle4 = child.state;
            if (child.state.name == "Idle12") idle12 = child.state;
        }

        if (idle3 != null) AddIdleTransition(from, idle3, 0);
        if (idle4 != null) AddIdleTransition(from, idle4, 1);
        if (idle12 != null) AddIdleTransition(from, idle12, 2);
    }

    private static void AddIdleTransition(AnimatorState from, AnimatorState to, int idleIndex)
    {
        var transition = from.AddTransition(to);
        transition.hasExitTime = false;
        transition.duration = 0.2f;
        transition.AddCondition(AnimatorConditionMode.Equals, 0, "Gait");
        transition.AddCondition(AnimatorConditionMode.Equals, idleIndex, "IdleIndex");
    }

    private static AnimatorState AddState(AnimatorStateMachine root, string name, AnimationClip clip)
    {
        var state = root.AddState(name);
        state.motion = clip;
        return state;
    }

    private static void AddGaitTransition(AnimatorState from, AnimatorState to, int gait)
    {
        var transition = from.AddTransition(to);
        transition.hasExitTime = false;
        transition.duration = 0.15f;
        transition.AddCondition(AnimatorConditionMode.Equals, gait, "Gait");
    }

    private static bool HasAnimationData(AnimationClip clip) => clip != null && clip.length > 0f;

    private static string ToAbsolute(string assetPath) =>
        Path.GetFullPath(Path.Combine(Application.dataPath, "..", assetPath));

    private sealed class SlugImportWindow : EditorWindow
    {
        private string _slug = "";

        public static void ShowWindow()
        {
            var window = GetWindow<SlugImportWindow>(utility: true, title: "Import Manifest");
            window.minSize = new Vector2(360, 72);
        }

        private void OnGUI()
        {
            EditorGUILayout.LabelField("Character slug (folder under Assets/Characters/)");
            _slug = EditorGUILayout.TextField(_slug);
            EditorGUILayout.Space();

            using (new EditorGUILayout.HorizontalScope())
            {
                GUI.enabled = !string.IsNullOrWhiteSpace(_slug);
                if (GUILayout.Button("Import"))
                {
                    ImportFromSlug(_slug.Trim());
                    Close();
                }

                GUI.enabled = true;
                if (GUILayout.Button("Cancel"))
                    Close();
            }
        }
    }
}
}
#endif
