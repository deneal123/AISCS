import { Matrix3, Triangle, Vector3 } from 'three';

// Display mesh coordinates are millimetres; the registered solver frame is µm.
// This places a passive recording contact. It never selects or excites neurons.
export const SURFACE_CONTACT_OFFSET_UM = 25;

// A normal-proximity test alone cannot classify a deep internal point. Use the
// signed solid angle of the original triangles, independently of display normals.
// Ambiguous/open surfaces remain unknown; do not label them as external.
export function surfaceContactLocation(pointMm, mesh) {
  const geometry = mesh?.userData?.sourceGeometry;
  if (!geometry || !Array.isArray(pointMm) || pointMm.length !== 3 || !pointMm.every(Number.isFinite)) return 'unknown';
  mesh.updateWorldMatrix(true, false);
  const point = mesh.worldToLocal(new Vector3(...pointMm));
  const positions = geometry.getAttribute('position'), indices = geometry.index;
  if (!positions) return 'unknown';
  const a = new Vector3(), b = new Vector3(), c = new Vector3(), cross = new Vector3();
  let solid = 0;
  for (let i = 0, count = indices ? indices.count : positions.count; i < count; i += 3) {
    [a, b, c].forEach((vertex, j) => vertex.fromBufferAttribute(positions, indices ? indices.getX(i + j) : i + j).sub(point));
    if (Math.min(a.length(), b.length(), c.length()) < 1e-9) return 'surface';
    solid += 2 * Math.atan2(a.dot(cross.crossVectors(b, c)), a.length() * b.length() * c.length()
      + a.dot(b) * c.length() + b.dot(c) * a.length() + c.dot(a) * b.length());
  }
  const winding = Math.abs(solid / (4 * Math.PI));
  return winding > .9 ? 'inside' : winding < .1 ? 'outside' : 'unknown';
}

export function surfaceContactPosition(pointMm, normal, originMm) {
  if (![pointMm, normal, originMm].every(value => Array.isArray(value) && value.length === 3
    && value.every(Number.isFinite))) throw new Error('surface_contact_geometry');
  const length = Math.hypot(...normal);
  if (length < 1e-12) throw new Error('surface_contact_normal');
  const coordinates = pointMm.map((value, axis) => (value - originMm[axis]) * 1000
    + normal[axis] / length * SURFACE_CONTACT_OFFSET_UM);
  // Reject an unsupported pick instead of silently moving it to a box boundary.
  if (coordinates.some(value => Math.abs(value) > 500)) throw new Error('surface_contact_domain');
  return Object.fromEntries(['x_um', 'y_um', 'z_um'].map((key, axis) => [key, Number(coordinates[axis].toFixed(3))]));
}

// Orient only contacts close to the outside of the registered source surface.
// A free-space or interior point must not be made to look surface-attached.
export function surfaceContactNormal(pointMm, mesh, maxOffsetUm = 75) {
  const geometry = mesh?.userData?.sourceGeometry;
  if (!geometry || !pointMm.every(Number.isFinite)) return null;
  mesh.updateWorldMatrix(true, false);
  const point = mesh.worldToLocal(new Vector3(...pointMm));
  const positions = geometry.getAttribute('position'), indices = geometry.index;
  const triangle = new Triangle(), nearest = new Vector3(), closest = new Vector3(), normal = new Vector3();
  let distance = Infinity;
  const count = indices ? indices.count : positions.count;
  for (let i = 0; i < count; i += 3) {
    [triangle.a, triangle.b, triangle.c].forEach((vertex, j) => vertex.fromBufferAttribute(positions, indices ? indices.getX(i + j) : i + j));
    triangle.closestPointToPoint(point, nearest);
    const squared = nearest.distanceToSquared(point);
    if (squared < distance) { distance = squared; closest.copy(nearest); triangle.getNormal(normal); }
  }
  const worldNearest = mesh.localToWorld(closest);
  const offset = new Vector3(...pointMm).sub(worldNearest);
  normal.applyNormalMatrix(new Matrix3().getNormalMatrix(mesh.matrixWorld));
  if (!Number.isFinite(distance) || offset.length() > maxOffsetUm / 1000 || offset.dot(normal) <= 0) return null;
  return normal;
}
