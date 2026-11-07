import * as THREE from 'three';
import { maleCnsNativePosition, maleCnsViewPosition } from '../connectome/connectomeMorphology';
import { surfaceContactLocation, SURFACE_CONTACT_OFFSET_UM } from '../scene/surfacePlacement';

// Display-only registration: snapping changes the proposed native-frame point,
// but does not validate tissue geometry or the body-to-connectome transform.
export function snapFieldContactToBody(nativePosition, body) {
  if (!Array.isArray(nativePosition) || nativePosition.length !== 3 || !nativePosition.every(Number.isFinite)) throw new Error('contact_position');
  const world = new THREE.Vector3(...maleCnsViewPosition(nativePosition));
  const triangle = new THREE.Triangle(), closest = new THREE.Vector3(), normal = new THREE.Vector3();
  let best = null;
  body.updateWorldMatrix(true, true);
  body.traverse(mesh => {
    const geometry = mesh.userData?.sourceGeometry;
    if (!mesh.isMesh || !geometry || /wing/i.test(mesh.name)) return;
    const position = geometry.getAttribute('position'), indices = geometry.index;
    if (!position) return;
    const local = mesh.worldToLocal(world.clone());
    for (let i = 0, count = indices ? indices.count : position.count; i < count; i += 3) {
      [triangle.a, triangle.b, triangle.c].forEach((vertex, j) => vertex.fromBufferAttribute(position, indices ? indices.getX(i + j) : i + j));
      triangle.closestPointToPoint(local, closest);
      const point = mesh.localToWorld(closest.clone()), distance = point.distanceToSquared(world);
      if (!best || distance < best.distance) {
        triangle.getNormal(normal).applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld)).normalize();
        if (normal.lengthSq() > 0) best = { point, normal: normal.clone(), distance, mesh };
      }
    }
  });
  if (!best) throw new Error('contact_surface_unavailable');
  let outside = best.point.clone().addScaledVector(best.normal, SURFACE_CONTACT_OFFSET_UM / 1000);
  if (surfaceContactLocation(outside.toArray(), best.mesh) === 'inside') {
    best.normal.negate();
    outside = best.point.clone().addScaledVector(best.normal, SURFACE_CONTACT_OFFSET_UM / 1000);
  }
  return { coordinates: maleCnsNativePosition(outside.toArray()).map(value => Number(value.toFixed(3))),
    normal: best.normal.toArray() };
}
