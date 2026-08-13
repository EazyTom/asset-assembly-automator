using UnityEngine;

namespace AssetAssembly.Import.Runtime
{
    [DisallowMultipleComponent]
    public class DriveController : MonoBehaviour
    {
        public float moveSpeed = 12f;
        public float turnSpeed = 90f;

        void Update()
        {
            var h = Input.GetAxis("Horizontal");
            var v = Input.GetAxis("Vertical");
            transform.Rotate(0f, h * turnSpeed * Time.deltaTime, 0f);
            transform.position += transform.forward * (v * moveSpeed * Time.deltaTime);
        }
    }
}
