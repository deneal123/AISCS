import * as THREE from 'three';
import { maleCnsNativePosition, maleCnsViewPosition, NATIVE_VIEW_MATRIX } from '../connectome/connectomeMorphology';

// Nearest point on the displayed, verified LOD meshes. It is a geometric
// proposal in the source coordinate frame, not a validated tissue boundary.
export function snapFieldContactToNeuropil(nativePosition, regions) {
  if (!Array.isArray(nativePosition) || nativePosition.length !== 3 || !nativePosition.every(Number.isFinite)) throw new Error('contact_position');
  const world = new THREE.Vector3(...maleCnsViewPosition(nativePosition));
  // The body view scales axes differently. Choose the nearest surface in the
  // original EM metric, not the visually distorted body-view metric.
  const nativeMatrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX);
  const nativePoint = world.clone().applyMatrix4(nativeMatrix);
  const bodyFromNative = nativeMatrix.clone().invert();
  regions.updateWorldMatrix(true, true);
  const candidates = regions.children.filter(mesh => mesh.isMesh && mesh.geometry?.getAttribute('position')).map(mesh => {
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    const box = mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld).applyMatrix4(nativeMatrix);
    return { mesh, lower: box.distanceToPoint(nativePoint) ** 2 };
  }).sort((a, b) => a.lower - b.lower);
  const triangle = new THREE.Triangle(), bodyTriangle = new THREE.Triangle(), closest = new THREE.Vector3();
  let best = null;
  for (const { mesh, lower } of candidates) {
    if (best && lower > best.distance) break;
    const positions = mesh.geometry.getAttribute('position'), indices = mesh.geometry.index;
    for (let i = 0, count = indices ? indices.count : positions.count; i < count; i += 3) {
      [bodyTriangle.a, bodyTriangle.b, bodyTriangle.c].forEach((vertex, j) => vertex.fromBufferAttribute(positions, indices ? indices.getX(i + j) : i + j).applyMatrix4(mesh.matrixWorld));
      triangle.a.copy(bodyTriangle.a).applyMatrix4(nativeMatrix);
      triangle.b.copy(bodyTriangle.b).applyMatrix4(nativeMatrix);
      triangle.c.copy(bodyTriangle.c).applyMatrix4(nativeMatrix);
      triangle.closestPointToPoint(nativePoint, closest);
      const distance = closest.distanceToSquared(nativePoint);
      if (!best || distance < best.distance) {
        const normal = bodyTriangle.getNormal(new THREE.Vector3());
        if (normal.lengthSq() > 0) best = { point: closest.clone().applyMatrix4(bodyFromNative), normal, distance, region: mesh.userData.region };
      }
    }
  }
  if (!best) throw new Error('neuropil_surface_unavailable');
  return { coordinates: maleCnsNativePosition(best.point.toArray()).map(value => Number(value.toFixed(3))),
    normal: best.normal.toArray(), region: best.region };
}
