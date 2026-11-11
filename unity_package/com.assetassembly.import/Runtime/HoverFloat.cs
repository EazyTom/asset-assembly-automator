using UnityEngine;

namespace AssetAssembly.Import.Runtime
{
    /// <summary>Continuous gentle hover for AAA Aircraft rigs.</summary>
    [AddComponentMenu("AAA/AAA Aircraft Hover Float")]
    [DisallowMultipleComponent]
    public class HoverFloat : MonoBehaviour
    {
        [Header("Hover")]
        [Min(0f)]
        [SerializeField] float hoverHeight = 0.8f;

        [SerializeField] bool followGround = true;

        [Header("Drift range (meters)")]
        [SerializeField] float sideAmplitude = 0.35f;
        [SerializeField] float verticalAmplitude = 0.18f;
        [SerializeField] float forwardAmplitude = 0.15f;

        [Header("Motion")]
        [Min(0.01f)]
        [SerializeField] float speed = 1f;

        [SerializeField] bool randomizePhase = true;

        [Min(0f)]
        [SerializeField] float tiltDegrees;

        static readonly Vector2 SideHz = new(0.037f, 0.061f);
        static readonly Vector2 UpHz = new(0.053f, 0.089f);
        static readonly Vector2 ForwardHz = new(0.043f, 0.071f);
        const float GroundSampleInterval = 0.1f;

        Vector3 origin;
        Quaternion baseRotation;
        float bottomOffset;
        float phase;
        float groundY;
        float groundSample;
        float nextGroundSample;
        float groundDampVelocity;
        float hoverHeightBlend = 1f;
        float resumeLiftDuration;

        public void ResumeIdle(float liftDuration = 1.5f)
        {
            origin = transform.position;
            baseRotation = transform.rotation;
            bottomOffset = transform.position.y - GetLowestPointY();
            groundY = groundSample = SampleGround(transform.position);
            nextGroundSample = Time.time + GroundSampleInterval;
            groundDampVelocity = 0f;
            hoverHeightBlend = liftDuration <= 0f ? 1f : 0f;
            resumeLiftDuration = liftDuration;
        }

        void Start()
        {
            origin = transform.position;
            baseRotation = transform.rotation;
            phase = randomizePhase ? Random.Range(0f, 100f) : 0f;
            bottomOffset = transform.position.y - GetLowestPointY();
            groundY = groundSample = SampleGround(transform.position);
        }

        void Update()
        {
            if (hoverHeightBlend < 1f && resumeLiftDuration > 0f)
            {
                hoverHeightBlend = Mathf.Min(1f, hoverHeightBlend + Time.deltaTime / resumeLiftDuration);
            }

            float t = (Time.time + phase) * speed;
            float side = Wave(t, SideHz);
            float rise = Wave(t + 11f, UpHz);
            float forward = Wave(t + 23f, ForwardHz);

            Vector3 target = origin;
            target.x += side * sideAmplitude;
            target.z += forward * forwardAmplitude;

            if (followGround)
            {
                if (Time.time >= nextGroundSample)
                {
                    nextGroundSample = Time.time + GroundSampleInterval;
                    groundSample = SampleGround(target);
                }

                groundY = Mathf.SmoothDamp(groundY, groundSample, ref groundDampVelocity, 0.6f);
            }

            target.y = groundY + bottomOffset + hoverHeight * hoverHeightBlend + rise * verticalAmplitude;
            transform.position = target;

            if (tiltDegrees > 0f)
            {
                transform.rotation = Quaternion.Euler(forward * tiltDegrees, 0f, -side * tiltDegrees) * baseRotation;
            }
        }

        static float Wave(float t, Vector2 hz)
        {
            const float tau = Mathf.PI * 2f;
            return Mathf.Sin(t * tau * hz.x) * 0.65f + Mathf.Sin(t * tau * hz.y) * 0.35f;
        }

        float SampleGround(Vector3 worldPosition)
        {
            Terrain terrain = Terrain.activeTerrain;
            if (terrain != null)
            {
                return terrain.SampleHeight(worldPosition) + terrain.transform.position.y;
            }

            if (Physics.Raycast(worldPosition + Vector3.up * 50f, Vector3.down, out RaycastHit hit, 200f))
            {
                return hit.point.y;
            }

            return origin.y - bottomOffset;
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
    }
}
