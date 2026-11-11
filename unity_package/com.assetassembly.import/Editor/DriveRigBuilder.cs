#if UNITY_EDITOR
using System;
using System.Linq;
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    public static class DriveRigBuilder
    {
        public const float DefaultTargetMeters = 4.2f;
        const float TargetWheelDiameter = 0.35f;
        const string NeonWheelSearchToken = "Neon Command Wheel";

        public static GameObject Build(GameObject model, float targetSizeMeters = DefaultTargetMeters, GameObject wheelPrefab = null)
        {
            var existing = model.GetComponentInParent<DriveController>();
            if (existing != null)
            {
                Selection.activeGameObject = existing.gameObject;
                return existing.gameObject;
            }

            string meshPath = AssetDatabase.GetAssetPath(model);
            if (!string.IsNullOrEmpty(meshPath))
            {
                MeshyHdImportUtility.FitImportedAssetToWorld(meshPath, targetSizeMeters);
                model = AssetDatabase.LoadAssetAtPath<GameObject>(meshPath);
            }

            GameObject rig = new($"{model.name} Rig");
            Undo.RegisterCreatedObjectUndo(rig, "Build Drive Rig");
            rig.transform.SetPositionAndRotation(model.transform.position, Quaternion.identity);

            Undo.SetTransformParent(model.transform, rig.transform, "Build Drive Rig");
            Undo.RecordObject(model.transform, "Build Drive Rig");
            model.transform.localPosition = Vector3.zero;
            model.transform.localScale = Vector3.one;

            DriveController drive = Undo.AddComponent<DriveController>(rig);
            drive.ApplyModelOrientation();
            drive.AlignNoseToLongestAxis();
            drive.DeriveWheelAnchorsFromBounds();

            SerializedObject serialized = new(drive);
            serialized.FindProperty("dashboardOffset").vector3Value = drive.DeriveDashboardOffset();
            serialized.FindProperty("autoDashboard").boolValue = false;
            serialized.ApplyModifiedPropertiesWithoutUndo();

            AudioSource engine = EnsureEngineAudio(model);
            serialized.Update();
            serialized.FindProperty("engineSource").objectReferenceValue = engine;
            serialized.ApplyModifiedPropertiesWithoutUndo();

            if (wheelPrefab == null)
            {
                wheelPrefab = ResolveDefaultWheelPrefab();
            }

            GameObject wheel = PlaceSteeringWheel(rig, drive, wheelPrefab);
            if (wheel != null)
            {
                serialized.Update();
                serialized.FindProperty("steeringWheel").objectReferenceValue = wheel.GetComponent<SteeringWheel>();
                drive.CaptureSteeringWheelTransform();
                serialized.FindProperty("steeringWheelLocalPosition").vector3Value = drive.SteeringWheelLocalPosition;
                serialized.FindProperty("steeringWheelLocalEuler").vector3Value = drive.SteeringWheelLocalEuler;
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }

            EnsureDashboardPanel(rig, drive);
            PlaceCabinFurniture(drive);
            float bottomOffset = rig.transform.position.y - GetLowestPointY(rig);
            HullUtility.DropToGround(rig.transform, bottomOffset);

            Selection.activeGameObject = rig;
            return rig;
        }

        /// <summary>
        /// Rescales an assembled rig so its longest hull axis matches <paramref name="targetLengthMeters"/>,
        /// then re-derives every placement that was measured from the old size.
        /// </summary>
        public static bool FitHullToLength(DriveController drive, float targetLengthMeters = DefaultTargetMeters)
        {
            if (drive == null || targetLengthMeters <= 0f)
            {
                return false;
            }

            Transform model = drive.Model;
            if (model == null || !drive.TryGetLocalHullBounds(out Bounds local))
            {
                return false;
            }

            float current = Mathf.Max(local.size.x, local.size.y, local.size.z);
            if (current < 0.0001f)
            {
                return false;
            }

            float factor = targetLengthMeters / current;
            if (Mathf.Abs(factor - 1f) < 0.01f)
            {
                return false;
            }

            Undo.RegisterFullObjectHierarchyUndo(drive.gameObject, "Fit Drive Hull");
            Undo.RecordObject(drive, "Fit Drive Hull");
            model.localScale *= factor;

            drive.DeriveWheelAnchorsFromBounds();
            SerializedObject serialized = new(drive);
            serialized.FindProperty("dashboardOffset").vector3Value = drive.DeriveDashboardOffset();
            serialized.FindProperty("autoDashboard").boolValue = false;
            serialized.ApplyModifiedProperties();

            PlaceCabinFurniture(drive);

            float bottomOffset = drive.transform.position.y - GetLowestPointY(drive.gameObject);
            HullUtility.DropToGround(drive.transform, bottomOffset);
            EditorUtility.SetDirty(drive);
            return true;
        }

        /// <summary>
        /// Positions the dashboard panel and steering wheel from hull proportions so the cabin
        /// layout survives a rescale instead of keeping offsets tuned for the old size.
        /// </summary>
        public static void PlaceCabinFurniture(DriveController drive)
        {
            if (drive == null || !drive.TryGetLocalHullBounds(out Bounds local))
            {
                return;
            }

            float forward = local.size.z * 0.10f;
            float drop = local.size.y * 0.09f;

            SerializedObject serialized = new(drive);
            SerializedProperty panelOffset = serialized.FindProperty("dashboardPanelLocalOffset");
            if (panelOffset != null)
            {
                panelOffset.vector3Value = new Vector3(0f, -drop, forward);
            }

            serialized.ApplyModifiedProperties();
            drive.SyncDashboardPanelTransform();

            Transform panel = drive.transform.Find("Dashboard");
            if (panel != null)
            {
                float panelWidth = local.size.x * 0.55f;
                panel.localScale = new Vector3(panelWidth, panelWidth * 0.42f, 1f);
            }

            SteeringWheel wheel = drive.SteeringWheelComponent;
            if (wheel == null)
            {
                return;
            }

            Undo.RecordObject(wheel.transform, "Place Steering Wheel");
            ScaleWheelToDiameter(wheel.transform, Mathf.Min(TargetWheelDiameter, local.size.x * 0.3f));
            wheel.transform.localPosition = drive.DashboardOffset + new Vector3(0f, -drop * 1.6f, forward * 0.75f);
            wheel.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);

            drive.CaptureSteeringWheelTransform();
            serialized.Update();
            serialized.FindProperty("steeringWheelLocalPosition").vector3Value = drive.SteeringWheelLocalPosition;
            serialized.FindProperty("steeringWheelLocalEuler").vector3Value = drive.SteeringWheelLocalEuler;
            serialized.ApplyModifiedProperties();
        }

        static void ScaleWheelToDiameter(Transform wheel, float diameter)
        {
            MeshFilter filter = wheel.GetComponentInChildren<MeshFilter>();
            if (filter == null || filter.sharedMesh == null || diameter <= 0f)
            {
                return;
            }

            Vector3 size = filter.sharedMesh.bounds.size;
            float widest = Mathf.Max(size.x, size.z);
            if (widest < 0.0001f)
            {
                return;
            }

            wheel.localScale = Vector3.one * (diameter / widest);
        }

        public static GameObject ReplaceSteeringWheel(DriveController drive, GameObject wheelPrefab = null)
        {
            if (drive == null)
            {
                return null;
            }

            if (wheelPrefab == null)
            {
                wheelPrefab = ResolveDefaultWheelPrefab();
            }

            Transform existing = drive.transform.Find("SteeringWheel");
            if (existing != null)
            {
                Undo.DestroyObjectImmediate(existing.gameObject);
            }

            GameObject wheel = PlaceSteeringWheel(drive.gameObject, drive, wheelPrefab);
            if (wheel == null)
            {
                return null;
            }

            SerializedObject serialized = new(drive);
            serialized.FindProperty("steeringWheel").objectReferenceValue = wheel.GetComponent<SteeringWheel>();
            drive.CaptureSteeringWheelTransform();
            serialized.FindProperty("steeringWheelLocalPosition").vector3Value = drive.SteeringWheelLocalPosition;
            serialized.FindProperty("steeringWheelLocalEuler").vector3Value = drive.SteeringWheelLocalEuler;
            serialized.ApplyModifiedProperties();
            EditorUtility.SetDirty(drive);
            return wheel;
        }

        public static GameObject ResolveDefaultWheelPrefab()
        {
            string[] guids = AssetDatabase.FindAssets($"{NeonWheelSearchToken} t:GameObject");
            string path = guids
                .Select(AssetDatabase.GUIDToAssetPath)
                .Where(p => p.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
                .OrderByDescending(p => p, StringComparer.OrdinalIgnoreCase)
                .FirstOrDefault();

            return string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<GameObject>(path);
        }

        static GameObject PlaceSteeringWheel(GameObject rig, DriveController drive, GameObject wheelPrefab)
        {
            Vector3 seat = rig.transform.TransformPoint(drive.DashboardOffset);
            Vector3 wheelPos = seat + rig.transform.forward * 0.4f - rig.transform.up * 0.15f;
            Quaternion wheelRot = Quaternion.LookRotation(rig.transform.forward, rig.transform.up) * Quaternion.Euler(90f, 0f, 0f);

            GameObject wheel;
            if (wheelPrefab != null)
            {
                wheel = (GameObject)PrefabUtility.InstantiatePrefab(wheelPrefab, rig.transform);
                wheel.name = "SteeringWheel";
            }
            else
            {
                wheel = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                wheel.name = "SteeringWheel";
                wheel.transform.SetParent(rig.transform, false);
                UnityEngine.Object.DestroyImmediate(wheel.GetComponent<Collider>());
            }

            Undo.RegisterCreatedObjectUndo(wheel, "Build Drive Rig");
            wheel.transform.SetPositionAndRotation(wheelPos, wheelRot);

            float diameter = TargetWheelDiameter;
            Renderer[] cabinRenderers = rig.GetComponentsInChildren<Renderer>();
            if (cabinRenderers.Length > 0)
            {
                Bounds cabin = cabinRenderers[0].bounds;
                for (int i = 1; i < cabinRenderers.Length; i++)
                {
                    cabin.Encapsulate(cabinRenderers[i].bounds);
                }

                diameter = Mathf.Min(TargetWheelDiameter, cabin.size.x * 0.3f);
            }

            Bounds wheelBounds = wheel.GetComponentInRendererBounds();
            if (wheelBounds.size.magnitude > 0.01f)
            {
                float scale = diameter / Mathf.Max(wheelBounds.size.x, wheelBounds.size.z);
                wheel.transform.localScale = Vector3.one * scale;
            }

            EnsureWheelCollider(wheel);

            SteeringWheel wheelComponent = wheel.GetComponent<SteeringWheel>();
            if (wheelComponent == null)
            {
                wheelComponent = Undo.AddComponent<SteeringWheel>(wheel);
            }

            SerializedObject wheelSerialized = new(wheelComponent);
            SerializedProperty handleProp = wheelSerialized.FindProperty("handle");
            if (handleProp != null && handleProp.objectReferenceValue == null)
            {
                handleProp.objectReferenceValue = wheel.transform;
                wheelSerialized.ApplyModifiedPropertiesWithoutUndo();
            }

            drive.CaptureSteeringWheelTransform();
            return wheel;
        }

        static void EnsureWheelCollider(GameObject wheel)
        {
            if (wheel.GetComponent<Collider>() != null)
            {
                return;
            }

            MeshFilter meshFilter = wheel.GetComponentInChildren<MeshFilter>();
            if (meshFilter != null && meshFilter.sharedMesh != null)
            {
                MeshCollider meshCollider = Undo.AddComponent<MeshCollider>(wheel);
                meshCollider.sharedMesh = meshFilter.sharedMesh;
                meshCollider.convex = true;
                return;
            }

            SphereCollider sphere = Undo.AddComponent<SphereCollider>(wheel);
            sphere.radius = 0.2f;
        }

        static void EnsureDashboardPanel(GameObject rig, DriveController drive)
        {
            Transform existing = rig.transform.Find("Dashboard");
            if (existing != null)
            {
                return;
            }

            GameObject panel = GameObject.CreatePrimitive(PrimitiveType.Quad);
            panel.name = "Dashboard";
            Undo.RegisterCreatedObjectUndo(panel, "Build Drive Rig");
            panel.transform.SetParent(rig.transform, false);
            panel.transform.localScale = new Vector3(0.6f, 0.25f, 1f);
            UnityEngine.Object.DestroyImmediate(panel.GetComponent<Collider>());
        }

        static AudioSource EnsureEngineAudio(GameObject model)
        {
            AudioSource existing = model.GetComponentInChildren<AudioSource>();
            if (existing != null)
            {
                return existing;
            }

            AudioSource engine = Undo.AddComponent<AudioSource>(model);
            engine.clip = HullUtility.LoadDefaultEngineClip();
            engine.loop = true;
            engine.playOnAwake = true;
            engine.spatialBlend = 1f;
            engine.volume = 0.5f;
            engine.rolloffMode = AudioRolloffMode.Linear;
            engine.maxDistance = 40f;
            return engine;
        }

        static float GetLowestPointY(GameObject rig)
        {
            Renderer[] renderers = rig.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return rig.transform.position.y;
            }

            Bounds bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            return bounds.min.y;
        }
    }

    static class RendererBoundsExtensions
    {
        public static Bounds GetComponentInRendererBounds(this GameObject go)
        {
            Renderer r = go.GetComponent<Renderer>();
            return r != null ? r.bounds : new Bounds(go.transform.position, Vector3.zero);
        }
    }
}
#endif
