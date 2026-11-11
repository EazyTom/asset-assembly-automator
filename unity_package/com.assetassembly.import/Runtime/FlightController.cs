using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
#if AAA_HAS_XRI
using Unity.XR.CoreUtils;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.Interactors.Visuals;
using UnityEngine.XR.Interaction.Toolkit.Locomotion;
#endif

namespace AssetAssembly.Import.Runtime
{
    /// <summary>AAA Aircraft flight controller with cockpit boarding, hover, and Input System bindings.</summary>
    [AddComponentMenu("AAA/AAA Aircraft Flight Controller")]
    [DisallowMultipleComponent]
    public class FlightController : MonoBehaviour
    {
        enum ShipState { Hovering, Flying, Settling, Landed }

        static FlightController activePilot;

        [Header("Boarding")]
        [SerializeField] float pilotRadius = 6f;
        [SerializeField] float disembarkDistance = 5f;
        [SerializeField] bool autoCockpit = true;
        [SerializeField] Vector3 cockpitOffset;

        [Header("Hover")]
        [Tooltip("When enabled, the craft drifts gently while idle (AAA Aircraft only).")]
        [SerializeField] bool hoverEnabled = true;

        [Header("Handling")]
        [SerializeField] float maxSpeed = 18f;
        [SerializeField] float acceleration = 0.9f;
        [SerializeField] float turnRate = 45f;
        [SerializeField] float climbRate = 6f;
        [SerializeField] float maxPitchAngle = 20f;
        [SerializeField] float maxBankAngle = 25f;
        [SerializeField] float attitudeSmoothing = 0.45f;

        [Header("Flight envelope")]
        [SerializeField] float minClearance = 2f;
        [SerializeField] float maxAltitude = 60f;

        [Header("Landing")]
        [SerializeField] float touchdownClearance = 0.6f;
        [SerializeField] float settleDuration = 1.2f;

        [Header("Model")]
        [SerializeField] float noseYawOffset;

        [Header("Audio")]
        [SerializeField] bool driveEngineAudio = true;
        [SerializeField] float maxPitchMultiplier = 1.6f;
        [SerializeField] AudioSource engineSource;

        ShipState state = ShipState.Hovering;

        [SerializeField, HideInInspector] Quaternion modelBaseLocalRotation = Quaternion.identity;
        [SerializeField, HideInInspector] bool baseRotationCaptured;

        HoverFloat hover;
        Transform model;
#if AAA_HAS_XRI
        XROrigin xrOrigin;
        CharacterController playerBody;
        Transform playerHead;
        Transform playerOriginalParent;
        LocomotionProvider[] locomotionProviders;
        XRBodyTransformer[] bodyTransformers;
        GameObject[] rayVisuals;
        readonly List<GameObject> suspendedRayVisuals = new();
#endif
        AudioSource engine;
        float engineVolumeBeforeIsolation;
        bool engineIsolated;

        InputAction attitudeAction;
        InputAction altitudeAction;
        InputAction throttleAction;
        InputAction brakeAction;
        InputAction landAction;

        float bottomOffset;
        float yaw;
        float pitch;
        float roll;
        float pitchVelocity;
        float rollVelocity;
        float speed;
        float speedVelocity;
        bool autoLanding;
        bool armed = true;

        float settleTimer;
        Vector3 settleStartPosition;
        Quaternion settleStartRotation;
        float settleGroundY;
        float idleReturnTimer;
        float clearance;

        float baseEnginePitch = 1f;
        float baseEngineVolume = 1f;

        public bool IsPiloted => state == ShipState.Flying;
        public bool IsAutoLanding => autoLanding;
        public float Speed => speed;
        public float MaxSpeed => maxSpeed;
        public float PitchAngle => pitch;
        public float RollAngle => roll;
        public float Heading => Mathf.Repeat(yaw, 360f);
        public float Clearance => clearance;
        public float MaxAltitude => maxAltitude;
        public Vector3 CockpitOffset => cockpitOffset;
        public bool HoverEnabled => hoverEnabled;

        float RearmRadius => Mathf.Min(pilotRadius * 1.5f, disembarkDistance * 0.8f);

        void Awake()
        {
            hover = GetComponent<HoverFloat>();
            engine = engineSource != null ? engineSource : GetComponentInChildren<AudioSource>();
#if AAA_HAS_XRI
            xrOrigin = FindFirstObjectByType<XROrigin>();
            if (xrOrigin != null)
            {
                playerBody = xrOrigin.GetComponent<CharacterController>();
                playerHead = xrOrigin.Camera != null ? xrOrigin.Camera.transform : null;
                locomotionProviders = xrOrigin.GetComponentsInChildren<LocomotionProvider>(true);
                bodyTransformers = xrOrigin.GetComponentsInChildren<XRBodyTransformer>(true);
                rayVisuals = CollectRayVisuals(xrOrigin);
            }
#endif
            if (engine != null)
            {
                baseEnginePitch = engine.pitch;
                baseEngineVolume = engine.volume;
            }

            BuildInputActions();
        }

        void Start()
        {
            ApplyNoseAlignment();
            bottomOffset = transform.position.y - GetLowestPointY();
            yaw = transform.eulerAngles.y;

            if (autoCockpit || cockpitOffset == Vector3.zero)
            {
                cockpitOffset = DeriveCockpitOffset();
            }

            if (!hoverEnabled && hover != null)
            {
                hover.enabled = false;
            }
        }

        public void ApplyNoseAlignment()
        {
            if (model == null)
            {
                model = transform.childCount > 0 ? transform.GetChild(0) : null;
            }

            if (model == null)
            {
                return;
            }

            if (!baseRotationCaptured)
            {
                modelBaseLocalRotation = model.localRotation;
                baseRotationCaptured = true;
            }

            model.localRotation = Quaternion.Euler(0f, noseYawOffset, 0f) * modelBaseLocalRotation;
        }

        public void FlipNose()
        {
            noseYawOffset = Mathf.Repeat(noseYawOffset + 180f, 360f);
            ApplyNoseAlignment();
            if (autoCockpit)
            {
                cockpitOffset = DeriveCockpitOffset();
            }
        }

        void OnDisable()
        {
            SetFlightInputEnabled(false);
            if (activePilot == this)
            {
                ReleasePlayer();
            }

            if (state != ShipState.Hovering)
            {
                autoLanding = false;
                speed = 0f;
                ResumeHoverIdle();
            }
        }

        void Update()
        {
            SetEngineIsolated(activePilot != null && activePilot != this);

            switch (state)
            {
                case ShipState.Hovering:
                    CheckForPilot();
                    break;
                case ShipState.Landed:
                    UpdateIdleReturn();
                    break;
                case ShipState.Flying:
                    UpdateFlight();
                    break;
                case ShipState.Settling:
                    UpdateSettle();
                    break;
            }
        }

        void CheckForPilot()
        {
#if AAA_HAS_XRI
            if (playerHead == null || (activePilot != null && activePilot != this))
            {
                return;
            }

            float distance = HorizontalDistanceToHull(playerHead.position);
            if (!armed)
            {
                if (distance > RearmRadius)
                {
                    armed = true;
                }

                return;
            }

            if (distance <= pilotRadius)
            {
                BeginFlight();
            }
#else
            if (Keyboard.current != null && Keyboard.current.wKey.wasPressedThisFrame)
            {
                BeginFlight();
            }
#endif
        }

        void BeginFlight()
        {
            idleReturnTimer = 0f;
            state = ShipState.Flying;
            activePilot = this;
            armed = false;
            autoLanding = false;

            if (hover != null)
            {
                hover.enabled = false;
            }

            yaw = transform.eulerAngles.y;
            pitch = 0f;
            roll = 0f;
            speed = 0f;

            SeatPlayer();
            SetFlightInputEnabled(true);
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
            xrOrigin.MoveCameraToWorldLocation(transform.TransformPoint(cockpitOffset));
#endif
        }

        void ReleasePlayer()
        {
            if (activePilot != this)
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
                if (playerBody != null)
                {
                    playerBody.enabled = true;
                }

                SetPlayerLocomotionEnabled(true);
            }
#endif
            activePilot = null;
        }

        void SetEngineIsolated(bool isolated)
        {
            if (engine == null || engineIsolated == isolated)
            {
                return;
            }

            if (isolated)
            {
                engineVolumeBeforeIsolation = engine.volume;
                engine.volume = 0f;
                engine.mute = true;
            }
            else
            {
                engine.mute = false;
                engine.volume = engineVolumeBeforeIsolation;
            }

            engineIsolated = isolated;
        }

        void UpdateFlight()
        {
            float dt = Time.deltaTime;
            Vector2 attitudeInput = attitudeAction.ReadValue<Vector2>();
            float altitudeInput = altitudeAction.ReadValue<Vector2>().y;
            float throttleInput = throttleAction.ReadValue<float>();
            float brakeInput = brakeAction.ReadValue<float>();

            if (landAction.WasPressedThisFrame())
            {
                autoLanding = !autoLanding;
            }

            if (autoLanding)
            {
                attitudeInput = Vector2.zero;
                throttleInput = 0f;
                brakeInput = 1f;
                altitudeInput = -0.6f;
            }

            float targetPitch = -attitudeInput.y * maxPitchAngle;
            float targetRoll = -attitudeInput.x * maxBankAngle;
            pitch = Mathf.SmoothDamp(pitch, targetPitch, ref pitchVelocity, attitudeSmoothing);
            roll = Mathf.SmoothDamp(roll, targetRoll, ref rollVelocity, attitudeSmoothing);
            yaw += attitudeInput.x * turnRate * dt;

            float targetSpeed = maxSpeed * Mathf.Clamp01(throttleInput - brakeInput);
            speed = Mathf.SmoothDamp(speed, targetSpeed, ref speedVelocity, acceleration);

            Quaternion heading = Quaternion.Euler(pitch, yaw, 0f);
            Vector3 position = transform.position;
            position += heading * Vector3.forward * (speed * dt);
            position.y += altitudeInput * climbRate * dt;

            position = ClampToEnvelope(position, out clearance);
            transform.SetPositionAndRotation(position, Quaternion.Euler(pitch, yaw, roll));

            UpdateEngineAudio();

            bool descending = altitudeInput < 0f || autoLanding;
            if (clearance <= touchdownClearance && descending && speed < maxSpeed * 0.35f)
            {
                BeginSettle();
            }
        }

        Vector3 ClampToEnvelope(Vector3 position, out float outClearance)
        {
            float groundY = SampleGround(position);
            float floorY = groundY + bottomOffset + minClearance;
            float ceilingY = groundY + bottomOffset + maxAltitude;
            float lowerBound = autoLanding || position.y < floorY ? groundY + bottomOffset : floorY;
            position.y = Mathf.Clamp(position.y, lowerBound, ceilingY);
            outClearance = position.y - bottomOffset - groundY;
            return position;
        }

        void BeginSettle()
        {
            state = ShipState.Settling;
            settleTimer = 0f;
            settleStartPosition = transform.position;
            settleStartRotation = transform.rotation;
            settleGroundY = SampleGround(settleStartPosition);
            SetFlightInputEnabled(false);

            if (engine != null && driveEngineAudio)
            {
                engine.pitch = baseEnginePitch;
                engine.volume = baseEngineVolume;
            }
        }

        void UpdateSettle()
        {
            settleTimer += Time.deltaTime;
            float t = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(settleTimer / settleDuration));
            Vector3 grounded = new(settleStartPosition.x, settleGroundY + bottomOffset, settleStartPosition.z);
            Quaternion level = Quaternion.Euler(0f, yaw, 0f);
            transform.SetPositionAndRotation(
                Vector3.Lerp(settleStartPosition, grounded, t),
                Quaternion.Slerp(settleStartRotation, level, t));

            if (t >= 1f)
            {
                CompleteLanding();
            }
        }

        void CompleteLanding()
        {
            state = ShipState.Landed;
            idleReturnTimer = 3f;
            autoLanding = false;
            speed = 0f;
            pitch = 0f;
            roll = 0f;
            ReleasePlayer();
            PlacePlayerBesideShip();
        }

        void UpdateIdleReturn()
        {
            idleReturnTimer -= Time.deltaTime;
            if (idleReturnTimer > 0f)
            {
                return;
            }

            ResumeHoverIdle();
        }

        void ResumeHoverIdle()
        {
            idleReturnTimer = 0f;
            if (hoverEnabled && hover != null)
            {
                hover.ResumeIdle();
                hover.enabled = true;
            }

            state = ShipState.Hovering;
        }

        void PlacePlayerBesideShip()
        {
#if AAA_HAS_XRI
            if (xrOrigin == null || playerHead == null)
            {
                return;
            }

            Vector3 sideways = Quaternion.Euler(0f, yaw, 0f) * Vector3.right;
            Vector3 spot = transform.position + sideways * disembarkDistance;
            spot.y = SampleGround(spot);
            float headHeight = playerHead.position.y - xrOrigin.transform.position.y;
            bool hadBody = playerBody != null && playerBody.enabled;
            if (hadBody)
            {
                playerBody.enabled = false;
            }

            xrOrigin.MoveCameraToWorldLocation(new Vector3(spot.x, spot.y + headHeight, spot.z));
            if (hadBody)
            {
                playerBody.enabled = true;
            }
#endif
        }

        public Vector3 DeriveCockpitOffset()
        {
            Renderer[] renderers = GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return new Vector3(0f, 0f, 1f);
            }

            Bounds local = new(transform.InverseTransformPoint(renderers[0].bounds.center), Vector3.zero);
            foreach (Renderer renderer in renderers)
            {
                Bounds world = renderer.bounds;
                for (int corner = 0; corner < 8; corner++)
                {
                    Vector3 point = world.center + Vector3.Scale(world.extents, new Vector3(
                        (corner & 1) == 0 ? -1f : 1f,
                        (corner & 2) == 0 ? -1f : 1f,
                        (corner & 4) == 0 ? -1f : 1f));
                    local.Encapsulate(transform.InverseTransformPoint(point));
                }
            }

            return new Vector3(
                local.center.x,
                local.center.y + local.extents.y * 0.48f,
                local.center.z + local.extents.z * 0.88f);
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

            SetTeleportEnabled(value);
        }

        static GameObject[] CollectRayVisuals(XROrigin origin)
        {
            List<GameObject> found = new();
            foreach (XRRayInteractor ray in origin.GetComponentsInChildren<XRRayInteractor>(true))
            {
                if (ray is not XRGazeInteractor)
                {
                    found.Add(ray.gameObject);
                }
            }

            foreach (CurveVisualController curve in origin.GetComponentsInChildren<CurveVisualController>(true))
            {
                found.Add(curve.gameObject);
            }

            return found.ToArray();
        }

        void SetTeleportEnabled(bool value)
        {
            if (value)
            {
                foreach (GameObject ray in suspendedRayVisuals)
                {
                    if (ray != null)
                    {
                        ray.SetActive(true);
                    }
                }

                suspendedRayVisuals.Clear();
                return;
            }

            if (rayVisuals != null)
            {
                foreach (GameObject ray in rayVisuals)
                {
                    if (ray == null || !ray.activeSelf)
                    {
                        continue;
                    }

                    suspendedRayVisuals.Add(ray);
                    ray.SetActive(false);
                }
            }
        }
#endif

        void UpdateEngineAudio()
        {
            if (engine == null || !driveEngineAudio)
            {
                return;
            }

            float t = maxSpeed > 0f ? Mathf.Clamp01(speed / maxSpeed) : 0f;
            engine.pitch = baseEnginePitch * Mathf.Lerp(1f, maxPitchMultiplier, t);
            engine.volume = baseEngineVolume * Mathf.Lerp(0.7f, 1f, t);
        }

        float HorizontalDistanceToHull(Vector3 worldPoint)
        {
            Renderer[] renderers = GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return HorizontalDistance(worldPoint, transform.position);
            }

            Bounds combined = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                combined.Encapsulate(renderers[i].bounds);
            }

            Vector3 closest = combined.ClosestPoint(worldPoint);
            return HorizontalDistance(worldPoint, closest);
        }

        static float HorizontalDistance(Vector3 a, Vector3 b)
        {
            a.y = 0f;
            b.y = 0f;
            return Vector3.Distance(a, b);
        }

        float SampleGround(Vector3 worldPosition)
        {
            float bestY = float.NegativeInfinity;
            Terrain terrain = Terrain.activeTerrain;
            if (terrain != null)
            {
                bestY = terrain.SampleHeight(worldPosition) + terrain.transform.position.y;
            }

            RaycastHit[] hits = Physics.RaycastAll(worldPosition + Vector3.up * 200f, Vector3.down, 400f);
            foreach (RaycastHit hit in hits)
            {
                if (hit.collider == null || hit.collider.isTrigger)
                {
                    continue;
                }

                if (hit.point.y > bestY)
                {
                    bestY = hit.point.y;
                }
            }

            return bestY > float.NegativeInfinity ? bestY : 0f;
        }

        float GetLowestPointY()
        {
            Renderer[] renderers = GetComponentsInChildren<Renderer>();
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
            attitudeAction = new InputAction("ShipAttitude", InputActionType.Value, expectedControlType: "Vector2");
            attitudeAction.AddBinding("<XRController>{RightHand}/thumbstick");
            attitudeAction.AddCompositeBinding("2DVector")
                .With("Up", "<Keyboard>/upArrow")
                .With("Down", "<Keyboard>/downArrow")
                .With("Left", "<Keyboard>/leftArrow")
                .With("Right", "<Keyboard>/rightArrow");
            attitudeAction.AddCompositeBinding("2DVector")
                .With("Left", "<Keyboard>/a")
                .With("Right", "<Keyboard>/d");

            altitudeAction = new InputAction("ShipAltitude", InputActionType.Value, expectedControlType: "Vector2");
            altitudeAction.AddBinding("<XRController>{LeftHand}/thumbstick");
            altitudeAction.AddCompositeBinding("2DVector")
                .With("Up", "<Keyboard>/e")
                .With("Down", "<Keyboard>/q");

            throttleAction = new InputAction("ShipThrottle", InputActionType.Value, expectedControlType: "Axis");
            throttleAction.AddBinding("<XRController>{LeftHand}/trigger");
            throttleAction.AddBinding("<Keyboard>/w");

            brakeAction = new InputAction("ShipBrake", InputActionType.Value, expectedControlType: "Axis");
            brakeAction.AddBinding("<XRController>{RightHand}/trigger");
            brakeAction.AddBinding("<Keyboard>/s");

            landAction = new InputAction("ShipLand", InputActionType.Button);
            landAction.AddBinding("<Keyboard>/l");
        }

        void SetFlightInputEnabled(bool value)
        {
            InputAction[] actions = { attitudeAction, altitudeAction, throttleAction, brakeAction, landAction };
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
            Vector3 seat = transform.TransformPoint(cockpitOffset);
            Gizmos.color = Color.cyan;
            Gizmos.DrawWireSphere(seat, 0.35f);
            Vector3 tip = seat + transform.forward * 1.2f;
            Gizmos.color = Color.green;
            Gizmos.DrawLine(seat, tip);
            Vector3 back = tip - transform.forward * 0.45f;
            Gizmos.DrawLine(tip, back + transform.right * 0.12f);
            Gizmos.DrawLine(tip, back - transform.right * 0.12f);
            Gizmos.DrawLine(tip, back + transform.up * 0.12f);
            Gizmos.DrawLine(tip, back - transform.up * 0.12f);
        }

        void OnDestroy()
        {
            InputAction[] actions = { attitudeAction, altitudeAction, throttleAction, brakeAction, landAction };
            foreach (InputAction action in actions)
            {
                action?.Dispose();
            }
        }
    }
}
