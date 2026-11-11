#if UNITY_EDITOR
using AssetAssembly.Import.Runtime;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    [CustomEditor(typeof(DriveController))]
    public class DriveControllerEditor : UnityEditor.Editor
    {
        const float SeatRadius = 0.35f;
        const float ForwardLength = 1.2f;
        const float MaxForwardLength = 2.5f;
        static readonly Color SeatColor = new(0.15f, 0.95f, 1f, 1f);
        static readonly Color ForwardColor = new(0.25f, 1f, 0.3f, 1f);
        static readonly Color WheelAnchorColor = new(1f, 0.55f, 0.1f, 1f);
        static readonly Color SteeringWheelColor = new(1f, 0.85f, 0.2f, 1f);
        static readonly Color PanelColor = new(0.95f, 0.45f, 1f, 1f);

        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();
            EditorGUILayout.Space(8f);
            EditorGUILayout.HelpBox(
                "Cyan seat = driver camera/boarding point. Magenta = dashboard panel. " +
                "Yellow handles = Neon steering wheel (grab in VR, not tire positions). " +
                "Orange discs = invisible drive physics raycast anchors (use Derive Wheel Anchors).",
                MessageType.Info);

            var controller = (DriveController)target;

            EditorGUILayout.LabelField("Orientation", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "Driving keeps the rig root yaw-only, so pitch/roll authored on the root is lost in play mode. " +
                "Flatten pushes it into the model, then aim the nose down the green arrow.",
                MessageType.None);

            if (GUILayout.Button("Fix Orientation (Flatten Rig + Align Nose)"))
            {
                RecordHierarchy(controller, "Fix Drive Orientation");
                bool flattened = controller.FlattenRootToYaw();
                bool turned = controller.AlignNoseToLongestAxis();
                RefreshDerivedPlacement(controller);
                Debug.Log(
                    $"[AAA] Drive orientation fixed on '{controller.name}': " +
                    $"root flattened={flattened}, nose quarter-turned={turned}, " +
                    $"model euler={controller.ModelOrientationEuler}.",
                    controller);
            }

            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button("Nose -90°"))
                {
                    RotateNose(controller, -90f);
                }

                if (GUILayout.Button("Flip Nose 180°"))
                {
                    RotateNose(controller, 180f);
                }

                if (GUILayout.Button("Nose +90°"))
                {
                    RotateNose(controller, 90f);
                }
            }

            EditorGUILayout.Space(8f);
            if (GUILayout.Button($"Fit Hull To {DriveRigBuilder.DefaultTargetMeters:F1}m + Re-seat Cabin"))
            {
                if (DriveRigBuilder.FitHullToLength(controller))
                {
                    serializedObject.Update();
                }
            }

            if (GUILayout.Button("Re-seat Cabin From Hull Proportions"))
            {
                DriveRigBuilder.PlaceCabinFurniture(controller);
                serializedObject.Update();
            }

            EditorGUILayout.Space(8f);
            if (GUILayout.Button("Derive Dashboard From Bounds"))
            {
                Undo.RecordObject(controller, "Derive Dashboard");
                SerializedProperty offsetProp = serializedObject.FindProperty("dashboardOffset");
                SerializedProperty autoProp = serializedObject.FindProperty("autoDashboard");
                offsetProp.vector3Value = controller.DeriveDashboardOffset();
                autoProp.boolValue = false;
                serializedObject.ApplyModifiedProperties();
                controller.SyncDashboardPanelTransform();
                EditorUtility.SetDirty(controller);
            }

            if (GUILayout.Button("Replace Steering Wheel With Neon Command Wheel"))
            {
                DriveRigBuilder.ReplaceSteeringWheel(controller);
            }

            if (GUILayout.Button("Sync Dashboard Panel To Seat"))
            {
                Undo.RecordObject(controller, "Sync Dashboard Panel");
                controller.SyncDashboardPanelTransform();
                EditorUtility.SetDirty(controller);
            }

            if (GUILayout.Button("Derive Wheel Anchors From Bounds"))
            {
                Undo.RecordObject(controller, "Derive Wheel Anchors");
                controller.DeriveWheelAnchorsFromBounds();
                EditorUtility.SetDirty(controller);
            }
        }

        void RotateNose(DriveController controller, float degrees)
        {
            RecordHierarchy(controller, "Rotate Drive Nose");
            controller.RotateNose(degrees);
            RefreshDerivedPlacement(controller);
        }

        static void RecordHierarchy(DriveController controller, string label)
        {
            Undo.RegisterFullObjectHierarchyUndo(controller.gameObject, label);
            Undo.RecordObject(controller, label);
        }

        void RefreshDerivedPlacement(DriveController controller)
        {
            controller.DeriveWheelAnchorsFromBounds();

            // The mutations above bypass SerializedObject, so resync before touching properties
            // or ApplyModifiedProperties would write the stale snapshot back over them.
            serializedObject.Update();
            SerializedProperty autoProp = serializedObject.FindProperty("autoDashboard");
            if (autoProp == null || autoProp.boolValue)
            {
                SerializedProperty offsetProp = serializedObject.FindProperty("dashboardOffset");
                if (offsetProp != null)
                {
                    offsetProp.vector3Value = controller.DeriveDashboardOffset();
                }
            }

            serializedObject.ApplyModifiedProperties();
            controller.ApplySteeringWheelTransform();
            controller.SyncDashboardPanelTransform();
            EditorUtility.SetDirty(controller);
            EditorSceneManager.MarkSceneDirty(controller.gameObject.scene);
        }

        void OnSceneGUI()
        {
            var controller = (DriveController)target;
            Transform rig = controller.transform;
            SerializedProperty offsetProp = serializedObject.FindProperty("dashboardOffset");
            SerializedProperty autoProp = serializedObject.FindProperty("autoDashboard");
            SerializedProperty wheelPosProp = serializedObject.FindProperty("steeringWheelLocalPosition");
            SerializedProperty wheelRotProp = serializedObject.FindProperty("steeringWheelLocalEuler");
            SerializedProperty panelOffsetProp = serializedObject.FindProperty("dashboardPanelLocalOffset");
            if (offsetProp == null)
            {
                return;
            }

            float hull = MeasureHullSize(rig);
            float radius = Mathf.Clamp(hull * 0.05f, SeatRadius, 3f);
            float arrow = Mathf.Clamp(hull * 0.08f, ForwardLength, MaxForwardLength);
            Vector3 seat = rig.TransformPoint(offsetProp.vector3Value);
            DrawDashboardSeatPreview(seat, rig.position, rig, radius, arrow);
            DrawDashboardPanelPreview(rig, offsetProp.vector3Value, panelOffsetProp?.vector3Value ?? Vector3.zero);
            DrawWheelAnchors(controller, rig);
            DrawSteeringWheelHandles(controller, rig, wheelPosProp, wheelRotProp, serializedObject);

            EditorGUI.BeginChangeCheck();
            Vector3 movedSeat = Handles.PositionHandle(seat, rig.rotation);
            if (EditorGUI.EndChangeCheck())
            {
                Undo.RecordObject(controller, "Move Dashboard Offset");
                offsetProp.vector3Value = rig.InverseTransformPoint(movedSeat);
                if (autoProp != null)
                {
                    autoProp.boolValue = false;
                }

                serializedObject.ApplyModifiedProperties();
                controller.SyncDashboardPanelTransform();
            }

            if (panelOffsetProp != null)
            {
                Vector3 panelLocal = offsetProp.vector3Value + panelOffsetProp.vector3Value;
                Vector3 panelWorld = rig.TransformPoint(panelLocal);
                EditorGUI.BeginChangeCheck();
                Vector3 movedPanel = Handles.PositionHandle(panelWorld, rig.rotation);
                if (EditorGUI.EndChangeCheck())
                {
                    Undo.RecordObject(controller, "Move Dashboard Panel");
                    panelOffsetProp.vector3Value = rig.InverseTransformPoint(movedPanel) - offsetProp.vector3Value;
                    serializedObject.ApplyModifiedProperties();
                    controller.SyncDashboardPanelTransform();
                }
            }
        }

        static void DrawDashboardSeatPreview(Vector3 seat, Vector3 pivot, Transform rig, float radius, float arrow)
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

        static void DrawDashboardPanelPreview(Transform rig, Vector3 dashboardOffset, Vector3 panelOffset)
        {
            Transform panel = rig.Find("Dashboard");
            Vector3 world = panel != null
                ? panel.position
                : rig.TransformPoint(dashboardOffset + panelOffset);

            Handles.color = PanelColor;
            Handles.DrawWireCube(world, new Vector3(0.6f, 0.25f, 0.02f));
        }

        void DrawSteeringWheelHandles(
            DriveController controller,
            Transform rig,
            SerializedProperty wheelPosProp,
            SerializedProperty wheelRotProp,
            SerializedObject serialized)
        {
            SteeringWheel wheel = controller.SteeringWheelComponent;
            if (wheel == null || wheelPosProp == null || wheelRotProp == null)
            {
                Handles.color = SteeringWheelColor;
                Vector3 hint = rig.TransformPoint(wheelPosProp != null ? wheelPosProp.vector3Value : Vector3.zero);
                Handles.Label(hint, "Steering wheel missing — use Replace button");
                return;
            }

            Transform wheelTransform = wheel.transform;
            Vector3 worldPos = wheelTransform.position;
            Quaternion worldRot = wheelTransform.rotation;

            Handles.color = new Color(SteeringWheelColor.r, SteeringWheelColor.g, SteeringWheelColor.b, 0.45f);
            Handles.DrawDottedLine(rig.TransformPoint(controller.DashboardOffset), worldPos, 4f);
            Handles.color = SteeringWheelColor;
            Handles.DrawWireDisc(worldPos, wheelTransform.up, 0.22f);
            Handles.DrawWireDisc(worldPos, wheelTransform.forward, 0.22f);

            EditorGUI.BeginChangeCheck();
            worldRot = Handles.RotationHandle(worldRot, worldPos);
            worldPos = Handles.PositionHandle(worldPos, worldRot);
            if (EditorGUI.EndChangeCheck())
            {
                Undo.RecordObject(controller, "Move Steering Wheel");
                Undo.RecordObject(wheelTransform, "Move Steering Wheel");
                wheelTransform.SetPositionAndRotation(worldPos, worldRot);
                wheelPosProp.vector3Value = wheelTransform.localPosition;
                wheelRotProp.vector3Value = wheelTransform.localEulerAngles;
                serialized.ApplyModifiedProperties();
            }
        }

        static void DrawWheelAnchors(DriveController controller, Transform rig)
        {
            Handles.color = WheelAnchorColor;
            DrawWheelAnchor(controller.FrontLeft, rig);
            DrawWheelAnchor(controller.FrontRight, rig);
            DrawWheelAnchor(controller.RearLeft, rig);
            DrawWheelAnchor(controller.RearRight, rig);
        }

        static void DrawWheelAnchor(DriveController.WheelAnchor anchor, Transform rig)
        {
            if (anchor.localPosition == Vector3.zero)
            {
                return;
            }

            Vector3 world = rig.TransformPoint(anchor.localPosition);
            Handles.DrawWireDisc(world, rig.up, 0.2f);
            Handles.DrawLine(world, world + Vector3.down * anchor.suspensionLength);
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
