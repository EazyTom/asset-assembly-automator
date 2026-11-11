using System;
using UnityEngine;
using UnityEngine.InputSystem;
#if AAA_HAS_XRI
using Unity.XR.CoreUtils;
using UnityEngine.XR.Interaction.Toolkit.Locomotion;
#endif

namespace AssetAssembly.Import.Runtime
{
    /// <summary>Four-wheel kinematic drive controller for AAA Vehicle rigs.</summary>
    [AddComponentMenu("AAA/AAA Vehicle Drive Controller")]
    [DisallowMultipleComponent]
    public class DriveController : MonoBehaviour
    {
        [Serializable]
        public struct WheelAnchor
        {
            public Vector3 localPosition;
            public float suspensionLength;
            public float groundOffset;
        }

        static DriveController activeDriver;

        [Header("Boarding")]
        [SerializeField] float enterRadius = 4f;
        [SerializeField] float exitDistance = 3f;
        [SerializeField] float reboardDelay = 0.75f;
        [SerializeField] bool autoDashboard = true;
        [SerializeField] Vector3 dashboardOffset;

        [Header("Wheels")]
        [SerializeField] WheelAnchor frontLeft;
        [SerializeField] WheelAnchor frontRight;
        [SerializeField] WheelAnchor rearLeft;
        [SerializeField] WheelAnchor rearRight;

        [Header("Drive")]
        [SerializeField] float maxSpeed = 14f;
        [SerializeField] float acceleration = 1.2f;
        [SerializeField] float maxSteerAngle = 32f;
        [SerializeField] float wheelBase = 2.6f;
        [SerializeField] float trackWidth = 1.6f;
        [SerializeField] LayerMask groundMask = ~0;

        [Header("Audio")]
        [SerializeField] AudioSource engineSource;
        [SerializeField] bool driveEngineAudio = true;

        [Header("Steering wheel")]
        [SerializeField] SteeringWheel steeringWheel;
        [SerializeField] Vector3 steeringWheelLocalPosition;
        [SerializeField] Vector3 steeringWheelLocalEuler;
        [SerializeField] Vector3 dashboardPanelLocalOffset = new(0f, 0.1f, -0.15f);

        [Header("Orientation")]
        [Tooltip("Extra rotation applied to the visual model so its nose points along rig forward (+Z).")]
        [SerializeField] Vector3 modelOrientationEuler;
        [Tooltip("Drive math owns the root and keeps it yaw-only. Pitch/roll authored on the root is pushed into the model instead of being discarded on the first driven frame.")]
        [SerializeField] bool flattenRootOnStart = true;
        [SerializeField, HideInInspector] Quaternion modelBaseLocalRotation = Quaternion.identity;
        [SerializeField, HideInInspector] bool baseRotationCaptured;

        Transform model;

        bool isDriven;
        float speed;
        float speedVelocity;
        float steerAngle;
        float yaw;
        float bottomOffset;
        float boardBlockedUntil;

#if AAA_HAS_XRI
        XROrigin xrOrigin;
        CharacterController playerBody;
        Transform playerHead;
        Transform playerOriginalParent;
        LocomotionProvider[] locomotionProviders;
        XRBodyTransformer[] bodyTransformers;
#endif

        InputAction gasAction;
        InputAction brakeAction;
        InputAction steerAction;
        InputAction exitAction;

        readonly RaycastHit[] groundHits = new RaycastHit[16];

        float baseEnginePitch = 1f;
        float baseEngineVolume = 1f;

        public bool IsDriven => isDriven;
        public float Speed => speed;
        public float MaxSpeed => maxSpeed;
        public float Heading => Mathf.Repeat(yaw, 360f);
        public float SteerAngle => steerAngle;
        public Vector3 DashboardOffset => dashboardOffset;
        public SteeringWheel SteeringWheelComponent => steeringWheel;
        public Vector3 SteeringWheelLocalPosition => steeringWheelLocalPosition;
        public Vector3 SteeringWheelLocalEuler => steeringWheelLocalEuler;
        public Vector3 ModelOrientationEuler => modelOrientationEuler;
        public WheelAnchor FrontLeft => frontLeft;
        public WheelAnchor FrontRight => frontRight;
        public WheelAnchor RearLeft => rearLeft;
        public WheelAnchor RearRight => rearRight;

        void Awake()
        {
            if (engineSource == null)
            {
                engineSource = GetComponentInChildren<AudioSource>();
            }

#if AAA_HAS_XRI
            xrOrigin = FindFirstObjectByType<XROrigin>();
            if (xrOrigin != null)
            {
                playerBody = xrOrigin.GetComponent<CharacterController>();
                playerHead = xrOrigin.Camera != null ? xrOrigin.Camera.transform : null;
                locomotionProviders = xrOrigin.GetComponentsInChildren<LocomotionProvider>(true);
                bodyTransformers = xrOrigin.GetComponentsInChildren<XRBodyTransformer>(true);
            }
#endif
            if (engineSource != null)
            {
                baseEnginePitch = engineSource.pitch;
                baseEngineVolume = engineSource.volume;
            }

            BuildInputActions();
        }

        void Start()
        {
            if (flattenRootOnStart)
            {
                FlattenRootToYaw();
            }

            ApplyModelOrientation();
            yaw = transform.eulerAngles.y;

            if (autoDashboard || dashboardOffset == Vector3.zero)
            {
                dashboardOffset = DeriveDashboardOffset();
            }

            if (frontLeft.localPosition == Vector3.zero && rearLeft.localPosition == Vector3.zero)
            {
                DeriveWheelAnchorsFromBounds();
            }

            bottomOffset = transform.position.y - GetLowestPointY();
            ApplySteeringWheelTransform();
            SyncDashboardPanelTransform();
        }

        /// <summary>Child holding the imported mesh, ignoring rig-authored props.</summary>
        public Transform Model
        {
            get
            {
                if (model == null)
                {
                    model = FindModelChild();
                }

                return model;
            }
        }

        /// <summary>
        /// Re-expresses root pitch/roll as model-local rotation so the pose survives play mode,
        /// where the drive math rewrites the root every frame as yaw-only.
        /// </summary>
        public bool FlattenRootToYaw()
        {
            Quaternion current = transform.rotation;
            Quaternion yawOnly = Quaternion.Euler(0f, current.eulerAngles.y, 0f);
            Quaternion delta = Quaternion.Inverse(yawOnly) * current;
            if (Quaternion.Angle(Quaternion.identity, delta) < 0.01f)
            {
                return false;
            }

            int count = transform.childCount;
            Transform[] children = new Transform[count];
            for (int i = 0; i < count; i++)
            {
                children[i] = transform.GetChild(i);
            }

            transform.rotation = yawOnly;
            foreach (Transform child in children)
            {
                child.localPosition = delta * child.localPosition;
                child.localRotation = delta * child.localRotation;
            }

            dashboardOffset = delta * dashboardOffset;
            dashboardPanelLocalOffset = delta * dashboardPanelLocalOffset;
            frontLeft.localPosition = delta * frontLeft.localPosition;
            frontRight.localPosition = delta * frontRight.localPosition;
            rearLeft.localPosition = delta * rearLeft.localPosition;
            rearRight.localPosition = delta * rearRight.localPosition;
            CaptureSteeringWheelTransform();

            Transform target = Model;
            if (target != null)
            {
                modelBaseLocalRotation = Quaternion.Inverse(Quaternion.Euler(modelOrientationEuler)) * target.localRotation;
                baseRotationCaptured = true;
            }

            return true;
        }

        public void ApplyModelOrientation()
        {
            Transform target = Model;
            if (target == null)
            {
                return;
            }

            if (!baseRotationCaptured)
            {
                modelBaseLocalRotation = target.localRotation;
                baseRotationCaptured = true;
            }

            target.localRotation = Quaternion.Euler(modelOrientationEuler) * modelBaseLocalRotation;
        }

        public void RotateNose(float degrees)
        {
            modelOrientationEuler.y = Mathf.Repeat(modelOrientationEuler.y + degrees, 360f);
            ApplyModelOrientation();
        }

        public void FlipNose()
        {
            RotateNose(180f);
        }

        /// <summary>Yaws the model a quarter turn when the hull is longer across X than Z.</summary>
        public bool AlignNoseToLongestAxis()
        {
            if (!TryGetLocalHullBounds(out Bounds local) || local.size.x <= local.size.z)
            {
                return false;
            }

            RotateNose(90f);
            return true;
        }

        Transform FindModelChild()
        {
            Transform fallback = null;
            for (int i = 0; i < transform.childCount; i++)
            {
                Transform child = transform.GetChild(i);
                if (child.name == "Dashboard" || (steeringWheel != null && child == steeringWheel.transform))
                {
                    continue;
                }

                fallback ??= child;
                if (child.GetComponentInChildren<Renderer>() != null)
                {
                    return child;
                }
            }

            return fallback;
        }

        public void ApplySteeringWheelTransform()
        {
            if (steeringWheel == null)
            {
                return;
            }

            steeringWheel.transform.localPosition = steeringWheelLocalPosition;
            steeringWheel.transform.localRotation = Quaternion.Euler(steeringWheelLocalEuler);
        }

        public void CaptureSteeringWheelTransform()
        {
            if (steeringWheel == null)
            {
                return;
            }

            steeringWheelLocalPosition = steeringWheel.transform.localPosition;
            steeringWheelLocalEuler = steeringWheel.transform.localEulerAngles;
        }

        public void SyncDashboardPanelTransform()
        {
            Transform panel = transform.Find("Dashboard");
            if (panel == null)
            {
                return;
            }

            panel.localPosition = dashboardOffset + dashboardPanelLocalOffset;
            panel.localRotation = Quaternion.identity;
        }

        void OnDisable()
        {
            SetDriveInputEnabled(false);
            if (activeDriver == this)
            {
                ReleasePlayer();
            }
        }

        void Update()
        {
            if (!isDriven)
            {
                CheckForDriver();
                return;
            }

            UpdateDrive();
        }

        void CheckForDriver()
        {
#if AAA_HAS_XRI
            if (playerHead == null || (activeDriver != null && activeDriver != this))
            {
                return;
            }

            if (Time.time < boardBlockedUntil)
            {
                return;
            }

            float distance = HorizontalDistanceToHull(playerHead.position);
            if (IsPlayerOnRoof(playerHead.position) || distance <= enterRadius)
            {
                BeginDrive();
            }
#else
            if (Keyboard.current != null && Keyboard.current.wKey.wasPressedThisFrame)
            {
                BeginDrive();
            }
#endif
        }

        void BeginDrive()
        {
            isDriven = true;
            activeDriver = this;
            boardBlockedUntil = 0f;
            yaw = transform.eulerAngles.y;
            SeatPlayer();
            SetDriveInputEnabled(true);
        }

        void SeatPlayer()
        {
#if AAA_HAS_XRI
            if (xrOrigin == null || playerHead == null)
            {
                return;
            }

            SetPlayerLocomotionEnabled(false);
            if (playerBody != null)
            {
                playerBody.enabled = false;
            }

            playerOriginalParent = xrOrigin.transform.parent;
            xrOrigin.transform.SetParent(transform, true);
            xrOrigin.MatchOriginUpCameraForward(Vector3.up, transform.forward);
            xrOrigin.MoveCameraToWorldLocation(transform.TransformPoint(dashboardOffset));

            // MoveCameraToWorldLocation drops the origin by the player's eye height to land the
            // camera on the seat, which can bury the rig below the cabin floor and the terrain.
            // Re-enabling the CharacterController down there depenetrates the player skyward.
            Vector3 originPosition = xrOrigin.transform.position;
            float floorY = Mathf.Max(CabinFloorWorldY(), SampleGround(originPosition));
            if (originPosition.y < floorY)
            {
                originPosition.y = floorY;
                xrOrigin.transform.position = originPosition;
            }
#endif
        }

        float CabinFloorWorldY()
        {
            return TryGetHullBounds(out Bounds hull) ? hull.min.y : transform.position.y;
        }

        void ReleasePlayer(bool useExitSpot = false)
        {
            if (activeDriver != this)
            {
                return;
            }

#if AAA_HAS_XRI
            if (xrOrigin != null)
            {
                if (gameObject.activeInHierarchy && gameObject.scene.isLoaded)
                {
                    xrOrigin.transform.SetParent(playerOriginalParent, true);
                }

                playerOriginalParent = null;

                // Move first: handing locomotion and the CharacterController back while the rig
                // is still inside the hull lets one depenetration step fling the player.
                if (useExitSpot)
                {
                    xrOrigin.transform.position = ResolveExitSpot();
                }

                if (playerBody != null)
                {
                    playerBody.enabled = true;
                }

                SetPlayerLocomotionEnabled(true);
            }
#endif
            activeDriver = null;
            isDriven = false;
        }

        /// <summary>
        /// Ground point clear of the hull. Kept outside <see cref="enterRadius"/> so stepping out
        /// does not immediately re-trigger boarding, while still allowing a walk back in.
        /// </summary>
        Vector3 ResolveExitSpot()
        {
            Vector3 sideways = Quaternion.Euler(0f, yaw, 0f) * Vector3.right;
            float clearance = Mathf.Max(exitDistance, enterRadius + 0.5f);
            float offset = (TryGetLocalHullBounds(out Bounds local) ? local.extents.x : 1f) + clearance;
            Vector3 spot = transform.position + sideways * offset;

            // Enforce the invariant rather than trusting the offset: hull shape and heading both
            // affect how far the boarding trigger reaches in this direction.
            for (int i = 0; i < 4 && HorizontalDistanceToHull(spot) <= enterRadius; i++)
            {
                offset += clearance * 0.5f;
                spot = transform.position + sideways * offset;
            }

            spot.y = SampleGround(spot);
            return spot;
        }

        void UpdateDrive()
        {
            float dt = Time.deltaTime;
            float gas = gasAction.ReadValue<float>();
            float brake = brakeAction.ReadValue<float>();
            float keyboardSteer = steerAction.ReadValue<float>();
            float wheelSteer = steeringWheel != null && steeringWheel.IsGrabbed
                ? steeringWheel.NormalizedValue * 2f - 1f
                : 0f;
            float steerInput = Mathf.Abs(wheelSteer) > 0.01f ? wheelSteer : keyboardSteer;

            if (exitAction.WasPressedThisFrame())
            {
                ReleasePlayer(useExitSpot: true);
                SetDriveInputEnabled(false);
                boardBlockedUntil = Time.time + reboardDelay;
                return;
            }

            float targetSpeed = maxSpeed * Mathf.Clamp(gas - brake, -0.35f, 1f);
            speed = Mathf.SmoothDamp(speed, targetSpeed, ref speedVelocity, acceleration);

            steerAngle = steerInput * maxSteerAngle;
            if (Mathf.Abs(speed) > 0.05f)
            {
                float turnRadius = wheelBase / Mathf.Tan(Mathf.Abs(steerAngle) * Mathf.Deg2Rad + 0.001f);
                float yawRate = (speed / turnRadius) * Mathf.Rad2Deg * Mathf.Sign(steerAngle);
                yaw += yawRate * dt;
            }

            Vector3 position = transform.position;
            Quaternion rotation = Quaternion.Euler(0f, yaw, 0f);
            position += rotation * Vector3.forward * (speed * dt);

            ApplySuspension(ref position, ref rotation);
            transform.SetPositionAndRotation(position, rotation);
            UpdateEngineAudio();
        }

        void ApplySuspension(ref Vector3 position, ref Quaternion rotation)
        {
            WheelAnchor[] wheels = { frontLeft, frontRight, rearLeft, rearRight };
            Vector3[] corners = new Vector3[4];
            float avgY = 0f;
            int grounded = 0;

            for (int i = 0; i < 4; i++)
            {
                Vector3 world = transform.TransformPoint(wheels[i].localPosition);
                if (TrySampleGroundBelow(world + Vector3.up * 2f, 8f, out RaycastHit hit))
                {
                    corners[i] = hit.point + Vector3.up * wheels[i].groundOffset;
                    avgY += corners[i].y;
                    grounded++;
                }
                else
                {
                    corners[i] = world;
                }
            }

            if (grounded > 0)
            {
                avgY /= grounded;
                position.y = avgY + bottomOffset;
            }

            if (grounded < 3)
            {
                return;
            }

            // Steering owns the heading; the contact patch only supplies pitch and roll. Deriving
            // the heading from the anchors too lets a bad anchor layout aim the hull at the sky.
            Vector3 forward = (corners[0] + corners[1]) * 0.5f - (corners[2] + corners[3]) * 0.5f;
            Vector3 right = (corners[1] + corners[3]) * 0.5f - (corners[0] + corners[2]) * 0.5f;
            Vector3 normal = Vector3.Cross(forward, right);
            if (normal.sqrMagnitude < 0.0001f)
            {
                return;
            }

            normal.Normalize();
            if (normal.y < 0f)
            {
                normal = -normal;
            }

            Vector3 heading = Vector3.ProjectOnPlane(rotation * Vector3.forward, normal);
            if (heading.sqrMagnitude > 0.0001f)
            {
                rotation = Quaternion.LookRotation(heading.normalized, normal);
            }
        }

        public void DeriveWheelAnchorsFromBounds()
        {
            if (!TryGetLocalHullBounds(out Bounds local))
            {
                return;
            }

            float length = local.size.z;
            float width = local.size.x;
            float axleInset = length * 0.15f;
            float track = width * 0.85f * 0.5f;
            float frontZ = local.center.z + length * 0.5f - axleInset;
            float rearZ = local.center.z - length * 0.5f + axleInset;
            float y = local.min.y;

            // bottomOffset already lifts the rig so the hull's lowest point (the tyres) meets the
            // contact patch, so any groundOffset here is pure float. suspensionLength is gizmo-only.
            float gizmo = Mathf.Max(0.1f, local.size.y * 0.25f);
            frontLeft = MakeAnchor(local.center.x - track, y, frontZ, gizmo);
            frontRight = MakeAnchor(local.center.x + track, y, frontZ, gizmo);
            rearLeft = MakeAnchor(local.center.x - track, y, rearZ, gizmo);
            rearRight = MakeAnchor(local.center.x + track, y, rearZ, gizmo);
            wheelBase = Vector3.Distance(frontLeft.localPosition, rearLeft.localPosition);
            trackWidth = Vector3.Distance(frontLeft.localPosition, frontRight.localPosition);
        }

        static WheelAnchor MakeAnchor(float x, float y, float z, float suspensionLength)
        {
            return new WheelAnchor
            {
                localPosition = new Vector3(x, y, z),
                groundOffset = 0f,
                suspensionLength = suspensionLength,
            };
        }

        public Vector3 DeriveDashboardOffset()
        {
            if (!TryGetLocalHullBounds(out Bounds local))
            {
                return new Vector3(0f, 1.1f, 0.5f);
            }

            return new Vector3(local.center.x, local.center.y + local.extents.y * 0.35f, local.center.z + local.extents.z * 0.15f);
        }

        /// <summary>
        /// Hull extents in rig-local space. Renderer.bounds is a world AABB, so it reports
        /// meaningless axes for a rotated model; mesh bounds keep length on Z and width on X.
        /// </summary>
        public bool TryGetLocalHullBounds(out Bounds local)
        {
            Renderer[] renderers = GetHullRenderers();
            local = default;
            bool started = false;
            foreach (Renderer renderer in renderers)
            {
                Bounds mesh = GetRendererLocalBounds(renderer, out Matrix4x4 toWorld);
                for (int corner = 0; corner < 8; corner++)
                {
                    Vector3 point = mesh.center + Vector3.Scale(mesh.extents, new Vector3(
                        (corner & 1) == 0 ? -1f : 1f,
                        (corner & 2) == 0 ? -1f : 1f,
                        (corner & 4) == 0 ? -1f : 1f));
                    Vector3 rigLocal = transform.InverseTransformPoint(toWorld.MultiplyPoint3x4(point));
                    if (!started)
                    {
                        local = new Bounds(rigLocal, Vector3.zero);
                        started = true;
                        continue;
                    }

                    local.Encapsulate(rigLocal);
                }
            }

            return started;
        }

        static Bounds GetRendererLocalBounds(Renderer renderer, out Matrix4x4 toWorld)
        {
            toWorld = renderer.transform.localToWorldMatrix;
            if (renderer is SkinnedMeshRenderer skinned)
            {
                return skinned.localBounds;
            }

            MeshFilter filter = renderer.GetComponent<MeshFilter>();
            if (filter != null && filter.sharedMesh != null)
            {
                return filter.sharedMesh.bounds;
            }

            toWorld = Matrix4x4.identity;
            return renderer.bounds;
        }

#if AAA_HAS_XRI
        void SetPlayerLocomotionEnabled(bool value)
        {
            if (locomotionProviders != null)
            {
                foreach (LocomotionProvider provider in locomotionProviders)
                {
                    if (provider != null)
                    {
                        provider.enabled = value;
                    }
                }
            }

            if (bodyTransformers != null)
            {
                foreach (XRBodyTransformer transformer in bodyTransformers)
                {
                    if (transformer != null)
                    {
                        transformer.enabled = value;
                    }
                }
            }
        }
#endif

        void UpdateEngineAudio()
        {
            if (engineSource == null || !driveEngineAudio)
            {
                return;
            }

            float t = maxSpeed > 0f ? Mathf.Clamp01(Mathf.Abs(speed) / maxSpeed) : 0f;
            engineSource.pitch = baseEnginePitch * Mathf.Lerp(0.85f, 1.4f, t);
            engineSource.volume = baseEngineVolume * Mathf.Lerp(0.6f, 1f, t);
        }

        bool IsPlayerOnRoof(Vector3 worldPoint)
        {
            if (!TryGetHullBounds(out Bounds bounds))
            {
                return false;
            }

            if (worldPoint.y < bounds.min.y + bounds.size.y * 0.45f)
            {
                return false;
            }

            const float pad = 0.35f;
            return worldPoint.x >= bounds.min.x - pad && worldPoint.x <= bounds.max.x + pad
                && worldPoint.z >= bounds.min.z - pad && worldPoint.z <= bounds.max.z + pad;
        }

        /// <summary>Renderers that make up the vehicle, excluding a seated player's rig.</summary>
        Renderer[] GetHullRenderers()
        {
            Transform source = Model;
            return source != null
                ? source.GetComponentsInChildren<Renderer>()
                : GetComponentsInChildren<Renderer>();
        }

        bool TryGetHullBounds(out Bounds bounds)
        {
            Renderer[] renderers = GetHullRenderers();
            if (renderers.Length == 0)
            {
                bounds = default;
                return false;
            }

            bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            return true;
        }

        float HorizontalDistanceToHull(Vector3 worldPoint)
        {
            if (!TryGetHullBounds(out Bounds combined))
            {
                return Vector3.Distance(new Vector3(worldPoint.x, 0f, worldPoint.z), new Vector3(transform.position.x, 0f, transform.position.z));
            }

            Vector3 closest = combined.ClosestPoint(worldPoint);
            return Vector3.Distance(new Vector3(worldPoint.x, 0f, worldPoint.z), new Vector3(closest.x, 0f, closest.z));
        }

        /// <summary>
        /// Nearest downward hit that is not part of this rig. Seating the player parents the XR
        /// rig (and its interactor colliders) under the vehicle, so an unfiltered cast would take
        /// the driver's own hand as "ground" and pump the car upward every frame.
        /// </summary>
        bool TrySampleGroundBelow(Vector3 origin, float distance, out RaycastHit best)
        {
            int count = Physics.RaycastNonAlloc(
                origin, Vector3.down, groundHits, distance, groundMask, QueryTriggerInteraction.Ignore);

            best = default;
            float nearest = float.MaxValue;
            for (int i = 0; i < count; i++)
            {
                RaycastHit hit = groundHits[i];
                if (hit.collider == null || hit.collider.transform.IsChildOf(transform))
                {
                    continue;
                }

                if (hit.distance < nearest)
                {
                    nearest = hit.distance;
                    best = hit;
                }
            }

            return nearest < float.MaxValue;
        }

        float SampleGround(Vector3 worldPosition)
        {
            if (TrySampleGroundBelow(worldPosition + Vector3.up * 50f, 200f, out RaycastHit hit))
            {
                return hit.point.y;
            }

            Terrain terrain = Terrain.activeTerrain;
            return terrain != null ? terrain.SampleHeight(worldPosition) + terrain.transform.position.y : worldPosition.y;
        }

        float GetLowestPointY()
        {
            Renderer[] renderers = GetHullRenderers();
            if (renderers.Length == 0)
            {
                return transform.position.y;
            }

            Bounds bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            return bounds.min.y;
        }

        void BuildInputActions()
        {
            gasAction = new InputAction("DriveGas", InputActionType.Value, expectedControlType: "Axis");
            gasAction.AddBinding("<XRController>{LeftHand}/trigger");
            gasAction.AddBinding("<Keyboard>/w");

            brakeAction = new InputAction("DriveBrake", InputActionType.Value, expectedControlType: "Axis");
            brakeAction.AddBinding("<XRController>{RightHand}/trigger");
            brakeAction.AddBinding("<Keyboard>/s");

            steerAction = new InputAction("DriveSteer", InputActionType.Value, expectedControlType: "Axis");
            steerAction.AddCompositeBinding("1DAxis")
                .With("Negative", "<Keyboard>/a")
                .With("Positive", "<Keyboard>/d");

            exitAction = new InputAction("DriveExit", InputActionType.Button);
            exitAction.AddBinding("<XRController>{RightHand}/primaryButton");
            exitAction.AddBinding("<Keyboard>/l");
        }

        void SetDriveInputEnabled(bool value)
        {
            InputAction[] actions = { gasAction, brakeAction, steerAction, exitAction };
            foreach (InputAction action in actions)
            {
                if (action == null)
                {
                    continue;
                }

                if (value)
                {
                    action.Enable();
                }
                else
                {
                    action.Disable();
                }
            }
        }

        void OnDrawGizmosSelected()
        {
            Vector3 seat = transform.TransformPoint(dashboardOffset);
            Gizmos.color = Color.cyan;
            Gizmos.DrawWireSphere(seat, 0.3f);
            Vector3 tip = seat + transform.forward * 1f;
            Gizmos.color = Color.green;
            Gizmos.DrawLine(seat, tip);

            Gizmos.color = Color.yellow;
            DrawWheelGizmo(frontLeft);
            DrawWheelGizmo(frontRight);
            DrawWheelGizmo(rearLeft);
            DrawWheelGizmo(rearRight);
        }

        void DrawWheelGizmo(WheelAnchor anchor)
        {
            Vector3 world = transform.TransformPoint(anchor.localPosition);
            Gizmos.DrawWireSphere(world, 0.2f);
            Gizmos.DrawLine(world, world + Vector3.down * anchor.suspensionLength);
        }

        void OnDestroy()
        {
            InputAction[] actions = { gasAction, brakeAction, steerAction, exitAction };
            foreach (InputAction action in actions)
            {
                action?.Dispose();
            }
        }
    }
}
