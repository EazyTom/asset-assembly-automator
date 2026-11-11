#if UNITY_EDITOR
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    public static class FlightRigBuilder
    {
        public static GameObject Build(GameObject model, float targetSizeMeters = 6f)
        {
            var existing = model.GetComponentInParent<FlightController>();
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
            Undo.RegisterCreatedObjectUndo(rig, "Build Flight Rig");
            rig.transform.SetPositionAndRotation(model.transform.position, Quaternion.identity);

            Undo.SetTransformParent(model.transform, rig.transform, "Build Flight Rig");
            Undo.RecordObject(model.transform, "Build Flight Rig");
            model.transform.localPosition = Vector3.zero;
            model.transform.localScale = Vector3.one;

            HoverFloat hover = Undo.AddComponent<HoverFloat>(rig);
            FlightController flight = Undo.AddComponent<FlightController>(rig);

            SerializedObject serialized = new(flight);
            serialized.FindProperty("noseYawOffset").floatValue = HullUtility.MeasureNoseYaw(rig.transform, model);
            serialized.FindProperty("autoCockpit").boolValue = false;
            serialized.FindProperty("hoverEnabled").boolValue = true;
            serialized.ApplyModifiedPropertiesWithoutUndo();

            flight.ApplyNoseAlignment();
            serialized.Update();
            serialized.FindProperty("cockpitOffset").vector3Value = flight.DeriveCockpitOffset();
            serialized.ApplyModifiedPropertiesWithoutUndo();

            AudioSource engine = EnsureEngineAudio(model);
            serialized.Update();
            serialized.FindProperty("engineSource").objectReferenceValue = engine;
            serialized.ApplyModifiedPropertiesWithoutUndo();

            FitRigToHull(rig);
            Selection.activeGameObject = rig;
            return rig;
        }

        public static void FitRigToHull(GameObject rig)
        {
            FlightController flight = rig.GetComponent<FlightController>();
            if (flight == null)
            {
                return;
            }

            Transform modelTransform = null;
            foreach (Transform child in rig.transform)
            {
                if (child.GetComponentInChildren<Renderer>() != null)
                {
                    modelTransform = child;
                    break;
                }
            }

            if (modelTransform == null)
            {
                return;
            }

            Vector3 meshWorld = modelTransform.position;
            Renderer[] renderers = modelTransform.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return;
            }

            Bounds bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            Undo.RecordObject(rig.transform, "Fit Rig To Hull");
            Undo.RecordObject(modelTransform, "Fit Rig To Hull");
            Vector3 rigPos = rig.transform.position;
            rig.transform.position = new Vector3(bounds.center.x, rigPos.y, bounds.center.z);
            modelTransform.localPosition = rig.transform.InverseTransformPoint(meshWorld);

            flight.ApplyNoseAlignment();
            SerializedObject serialized = new(flight);
            serialized.FindProperty("cockpitOffset").vector3Value = flight.DeriveCockpitOffset();
            serialized.FindProperty("autoCockpit").boolValue = false;
            serialized.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(rig);
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
            engine.maxDistance = 60f;
            return engine;
        }
    }
}
#endif
