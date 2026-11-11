using System;
using UnityEngine;
#if AAA_HAS_XRI
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactables;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
#endif

namespace AssetAssembly.Import.Runtime
{
    /// <summary>Knob-style steering wheel interactable for AAA Vehicle rigs.</summary>
    [AddComponentMenu("AAA/AAA Vehicle Steering Wheel")]
    [DisallowMultipleComponent]
    public class SteeringWheel : MonoBehaviour
    {
#if AAA_HAS_XRI
        [SerializeField] Transform handle;
        [SerializeField] float minAngle = -225f;
        [SerializeField] float maxAngle = 225f;
        [SerializeField] float springSpeed = 8f;

        float currentAngle;
        bool isGrabbed;
        WheelInteractable interactable;
        Quaternion handleBaseRotation;
        bool handleBaseCaptured;

        public bool IsGrabbed => isGrabbed;
        public float NormalizedValue => Mathf.InverseLerp(minAngle, maxAngle, currentAngle);

        void Awake()
        {
            // Unity's fake-null means ??= would leave an unassigned field alone and throw later.
            if (handle == null)
            {
                handle = transform;
            }

            interactable = gameObject.AddComponent<WheelInteractable>();
            interactable.grabbed = OnGrabbed;
            interactable.released = OnReleased;
            interactable.angleDelta = ApplyDelta;
        }

        void Update()
        {
            if (!handleBaseCaptured)
            {
                // First Update runs after every Start, so the rig has finished mounting the wheel.
                handleBaseRotation = handle.localRotation;
                handleBaseCaptured = true;
            }

            if (!isGrabbed)
            {
                currentAngle = Mathf.Lerp(currentAngle, 0f, Time.deltaTime * springSpeed);
            }

            handle.localRotation = handleBaseRotation * Quaternion.Euler(0f, currentAngle, 0f);
        }

        void OnGrabbed() => isGrabbed = true;
        void OnReleased() => isGrabbed = false;

        void ApplyDelta(float delta) => currentAngle = Mathf.Clamp(currentAngle + delta, minAngle, maxAngle);

        class WheelInteractable : XRBaseInteractable
        {
            public Action grabbed;
            public Action released;
            public Action<float> angleDelta;

            float lastAngle;

            protected override void OnSelectEntered(SelectEnterEventArgs args)
            {
                base.OnSelectEntered(args);
                lastAngle = GetInteractorAngle(args.interactorObject);
                grabbed?.Invoke();
            }

            protected override void OnSelectExited(SelectExitEventArgs args)
            {
                base.OnSelectExited(args);
                released?.Invoke();
            }

            public override void ProcessInteractable(XRInteractionUpdateOrder.UpdatePhase updatePhase)
            {
                base.ProcessInteractable(updatePhase);
                if (!isSelected || updatePhase != XRInteractionUpdateOrder.UpdatePhase.Dynamic)
                {
                    return;
                }

                float angle = GetInteractorAngle(interactorsSelecting[0]);
                float delta = Mathf.DeltaAngle(lastAngle, angle);
                lastAngle = angle;
                angleDelta?.Invoke(delta);
            }

            float GetInteractorAngle(IXRSelectInteractor interactor)
            {
                Vector3 local = transform.InverseTransformPoint(interactor.GetAttachTransform(this).position);
                return Mathf.Atan2(local.x, local.z) * Mathf.Rad2Deg;
            }
        }
#else
        public bool IsGrabbed => false;
        public float NormalizedValue => 0.5f;
#endif
    }
}
