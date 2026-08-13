using UnityEngine;

namespace AssetAssembly.Import.Runtime
{
/// <summary>
/// Cycles Idle3 / Idle4 / Idle12 while standing, then occasionally walks an oval on terrain
/// before returning to idle. Expects animator parameters Gait (0=idle, 1=walk) and IdleIndex (0-2).
/// </summary>
[RequireComponent(typeof(Animator))]
public class CharacterOvalPatrol : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private Terrain terrain;
    [SerializeField] private Vector3 center;
    [SerializeField] private float radiusX = 18f;
    [SerializeField] private float radiusZ = 12f;
    [SerializeField] private float angularSpeed = 0.35f;
    [SerializeField] private float heightOffset = 0.05f;
    [SerializeField] private float minIdleSeconds = 5f;
    [SerializeField] private float maxIdleSeconds = 14f;
    [SerializeField] private float walkSeconds = 10f;
    [SerializeField] private float walkChanceAfterIdle = 0.35f;

    private float _theta;
    private float _segmentTimer;
    private int _idleIndex;
    private bool _walking;

    private void Reset()
    {
        animator = GetComponent<Animator>();
    }

    private void Awake()
    {
        if (animator == null)
            animator = GetComponent<Animator>();
    }

    private void Start()
    {
        if (terrain == null)
            terrain = Terrain.activeTerrain;

        if (center == Vector3.zero)
            center = transform.position;

        var offset = transform.position - center;
        if (radiusX > 0.01f && radiusZ > 0.01f)
            _theta = Mathf.Atan2(offset.z / radiusZ, offset.x / radiusX);

        BeginIdleSegment();
    }

    private void Update()
    {
        if (animator == null)
            return;

        _segmentTimer -= Time.deltaTime;

        if (_walking)
        {
            animator.SetInteger("Gait", 1);
            MoveAlongOval();
            if (_segmentTimer <= 0f)
                BeginIdleSegment();
            return;
        }

        animator.SetInteger("Gait", 0);
        animator.SetInteger("IdleIndex", _idleIndex);

        if (_segmentTimer > 0f)
            return;

        _idleIndex = (_idleIndex + 1) % 3;
        if (Random.value < walkChanceAfterIdle)
            BeginWalkSegment();
        else
            BeginIdleSegment();
    }

    private void BeginIdleSegment()
    {
        _walking = false;
        animator.SetInteger("Gait", 0);
        animator.SetInteger("IdleIndex", _idleIndex);
        _segmentTimer = Random.Range(minIdleSeconds, maxIdleSeconds);
    }

    private void BeginWalkSegment()
    {
        _walking = true;
        animator.SetInteger("Gait", 1);
        _segmentTimer = walkSeconds;
    }

    private void MoveAlongOval()
    {
        _theta += angularSpeed * Time.deltaTime;

        var target = center + new Vector3(
            Mathf.Cos(_theta) * radiusX,
            0f,
            Mathf.Sin(_theta) * radiusZ);

        if (terrain != null)
            target.y = terrain.SampleHeight(target) + heightOffset;

        var toTarget = target - transform.position;
        toTarget.y = 0f;

        if (toTarget.sqrMagnitude > 0.0001f)
        {
            var desiredRotation = Quaternion.LookRotation(toTarget.normalized, Vector3.up);
            transform.rotation = Quaternion.Slerp(
                transform.rotation,
                desiredRotation,
                8f * Time.deltaTime);
        }

        transform.position = Vector3.MoveTowards(
            transform.position,
            target,
            (radiusX + radiusZ) * 0.25f * Mathf.Abs(angularSpeed) * Time.deltaTime);
    }
}
}
