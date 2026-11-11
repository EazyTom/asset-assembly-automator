#if UNITY_EDITOR
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    [CustomEditor(typeof(FlightController))]
    public class FlightControllerEditor : UnityEditor.Editor
    {
        const float SeatRadius = 0.35f;
        const float ForwardLength = 1.2f;
        const float MaxForwardLength = 2.5f;
        static readonly Color SeatColor = new(0.15f, 0.95f, 1f, 1f);
        static readonly Color ForwardColor = new(0.25f, 1f, 0.3f, 1f);

        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();
            EditorGUILayout.Space(8f);
            EditorGUILayout.HelpBox(
                "Scene view shows the cockpit seat (cyan) and travel direction (green). " +
                "Drag the move handle at the seat to set Cockpit Offset.",
                MessageType.Info);

            var controller = (FlightController)target;
            if (GUILayout.Button("Flip Nose 180°"))
            {
                Undo.RecordObject(controller, "Flip Nose 180");
                controller.FlipNose();
                EditorUtility.SetDirty(controller);
            }

            if (GUILayout.Button("Apply Nose Alignment"))
            {
                Undo.RecordObject(controller, "Apply Nose Alignment");
                controller.ApplyNoseAlignment();
                EditorUtility.SetDirty(controller);
            }
        }

        void OnSceneGUI()
        {
            var controller = (FlightController)target;
            Transform rig = controller.transform;
            SerializedProperty offsetProp = serializedObject.FindProperty("cockpitOffset");
            SerializedProperty autoProp = serializedObject.FindProperty("autoCockpit");
            if (offsetProp == null)
            {
                return;
            }

            float hull = MeasureHullSize(rig);
            float radius = Mathf.Clamp(hull * 0.05f, SeatRadius, 3f);
            float arrow = Mathf.Clamp(hull * 0.08f, ForwardLength, MaxForwardLength);
            Vector3 seat = rig.TransformPoint(offsetProp.vector3Value);
            DrawSeatPreview(seat, rig.position, rig, radius, arrow);

            EditorGUI.BeginChangeCheck();
            Vector3 moved = Handles.PositionHandle(seat, rig.rotation);
            if (EditorGUI.EndChangeCheck())
            {
                Undo.RecordObject(controller, "Move Cockpit Offset");
                offsetProp.vector3Value = rig.InverseTransformPoint(moved);
                if (autoProp != null)
                {
                    autoProp.boolValue = false;
                }

                serializedObject.ApplyModifiedProperties();
            }
        }

        static void DrawSeatPreview(Vector3 seat, Vector3 pivot, Transform rig, float radius, float arrow)
        {
            Handles.zTest = UnityEngine.Rendering.CompareFunction.Always;
            Handles.color = new Color(SeatColor.r, SeatColor.g, SeatColor.b, 0.45f);
            Handles.DrawDottedLine(pivot, seat, 4f);
            Handles.color = SeatColor;
            Handles.DrawWireDisc(seat, rig.up, radius);
            Handles.DrawWireDisc(seat, rig.forward, radius);
            Handles.DrawWireDisc(seat, rig.right, radius);
            Handles.SphereHandleCap(0, seat, Quaternion.identity, radius * 0.4f, EventType.Repaint);
            Handles.color = ForwardColor;
            Handles.ArrowHandleCap(0, seat, Quaternion.LookRotation(rig.forward, rig.up), arrow, EventType.Repaint);
        }

        static float MeasureHullSize(Transform rig)
        {
            Renderer[] renderers = rig.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return 4f;
            }

            Bounds bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            return Mathf.Max(bounds.size.x, bounds.size.y, bounds.size.z);
        }
    }
}
#endif
