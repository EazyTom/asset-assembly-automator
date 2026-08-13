using UnityEngine;

namespace AssetAssembly.Import.Runtime
{
    [DisallowMultipleComponent]
    public class FlightController : MonoBehaviour
    {
        public float thrust = 20f;
        public float pitchSpeed = 45f;
        public float yawSpeed = 60f;
        float _throttle;

        void Update()
        {
            if (Input.GetKey(KeyCode.LeftShift))
                _throttle = Mathf.Min(1f, _throttle + Time.deltaTime);
            if (Input.GetKey(KeyCode.LeftControl))
                _throttle = Mathf.Max(0f, _throttle - Time.deltaTime);

            var pitch = Input.GetAxis("Vertical") * pitchSpeed * Time.deltaTime;
            var yaw = Input.GetAxis("Horizontal") * yawSpeed * Time.deltaTime;
            transform.Rotate(pitch, yaw, 0f);
            transform.position += transform.forward * (_throttle * thrust * Time.deltaTime);
        }
    }
}
