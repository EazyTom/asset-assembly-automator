#if UNITY_EDITOR
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace AssetAssembly.Import.Editor
{
    /// <summary>Hull measurement helpers shared by flight and drive rig builders.</summary>
    public static class HullUtility
    {
        const int SampleBudget = 20000;
        const float EndBandFraction = 0.22f;

        public static float MeasureNoseYaw(Transform rig, GameObject model)
        {
            MeshFilter[] filters = model.GetComponentsInChildren<MeshFilter>();
            if (filters.Length == 0)
            {
                return 0f;
            }

            int total = 0;
            foreach (MeshFilter filter in filters)
            {
                if (filter.sharedMesh != null)
                {
                    total += filter.sharedMesh.vertexCount;
                }
            }

            if (total == 0)
            {
                return 0f;
            }

            int stride = Mathf.Max(1, total / SampleBudget);
            var points = new List<Vector3>(SampleBudget + filters.Length);

            foreach (MeshFilter filter in filters)
            {
                Mesh mesh = filter.sharedMesh;
                if (mesh == null)
                {
                    continue;
                }

                Vector3[] vertices = mesh.vertices;
                for (int i = 0; i < vertices.Length; i += stride)
                {
                    points.Add(rig.InverseTransformPoint(filter.transform.TransformPoint(vertices[i])));
                }
            }

            if (points.Count < 8)
            {
                return 0f;
            }

            Vector3 centre = Vector3.zero;
            foreach (Vector3 point in points)
            {
                centre += point;
            }

            centre /= points.Count;

            double xx = 0d, xz = 0d, zz = 0d;
            foreach (Vector3 point in points)
            {
                double dx = point.x - centre.x;
                double dz = point.z - centre.z;
                xx += dx * dx;
                xz += dx * dz;
                zz += dz * dz;
            }

            Vector3 axis;
            if (System.Math.Abs(xz) > 1e-9)
            {
                double trace = xx + zz;
                double determinant = xx * zz - xz * xz;
                double major = trace / 2d + System.Math.Sqrt(System.Math.Max(0d, trace * trace / 4d - determinant));
                axis = new Vector3((float)(major - zz), 0f, (float)xz).normalized;
            }
            else
            {
                axis = xx >= zz ? Vector3.right : Vector3.forward;
            }

            float min = float.MaxValue;
            float max = float.MinValue;
            foreach (Vector3 point in points)
            {
                float along = Vector3.Dot(point - centre, axis);
                min = Mathf.Min(min, along);
                max = Mathf.Max(max, along);
            }

            Vector3 lateral = Vector3.Cross(Vector3.up, axis).normalized;
            float highCut = max - (max - min) * EndBandFraction;
            float lowCut = min + (max - min) * EndBandFraction;

            double highSum = 0d, lowSum = 0d;
            int highCount = 0, lowCount = 0;

            foreach (Vector3 point in points)
            {
                Vector3 offset = point - centre;
                float along = Vector3.Dot(offset, axis);
                float radius = new Vector2(Vector3.Dot(offset, lateral), offset.y).magnitude;

                if (along > highCut)
                {
                    highSum += radius;
                    highCount++;
                }
                else if (along < lowCut)
                {
                    lowSum += radius;
                    lowCount++;
                }
            }

            double highRadius = highCount > 0 ? highSum / highCount : 0d;
            double lowRadius = lowCount > 0 ? lowSum / lowCount : 0d;
            Vector3 nose = highRadius < lowRadius ? axis : -axis;

            return Mathf.Repeat(-Mathf.Atan2(nose.x, nose.z) * Mathf.Rad2Deg, 360f);
        }

        public static float MeasureLongestAxis(GameObject root)
        {
            Renderer[] renderers = root.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
            {
                return 1f;
            }

            Bounds bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            return Mathf.Max(bounds.size.x, bounds.size.y, bounds.size.z);
        }

        public static void DropToGround(Transform rig, float bottomOffset)
        {
            Vector3 pos = rig.position;
            float ground = SampleGround(pos);
            rig.position = new Vector3(pos.x, ground + bottomOffset, pos.z);
        }

        public static float SampleGround(Vector3 worldPosition)
        {
            float bestY = float.NegativeInfinity;
            Terrain terrain = Terrain.activeTerrain;
            if (terrain != null)
            {
                bestY = terrain.SampleHeight(worldPosition) + terrain.transform.position.y;
            }

            if (Physics.Raycast(worldPosition + Vector3.up * 200f, Vector3.down, out RaycastHit hit, 400f))
            {
                bestY = Mathf.Max(bestY, hit.point.y);
            }

            return bestY > float.NegativeInfinity ? bestY : worldPosition.y;
        }

        public static AudioClip LoadDefaultEngineClip()
        {
            return AssetDatabase.LoadAssetAtPath<AudioClip>(
                "Packages/com.assetassembly.import/Runtime/Audio/engine_loop.wav");
        }
    }
}
#endif
