import * as THREE from 'three';
import { maleCnsViewPosition, NATIVE_VIEW_MATRIX } from './connectome/connectomeMorphology';

// These are threshold samples at solver midpoints, not axonal wave paths.
export function activeCompartmentEvents(events, timeMs, windowMs = .75) {
  if (!Array.isArray(events) || !Number.isFinite(timeMs)) return [];
  return events.filter(event => Array.isArray(event) && event.length === 6
    && Number.isFinite(event[1]) && event[1] <= timeMs && timeMs - event[1] < windowMs
    && event.slice(3).every(Number.isFinite));
}

export function createCompartmentEventLayer(preview) {
  const events = Array.isArray(preview?.events) ? preview.events : [];
  const positions = new Float32Array(events.length * 3);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage));
  geometry.setDrawRange(0, 0);
  const material = new THREE.PointsMaterial({ color: 0xffc16b, size: .013, transparent: true,
    opacity: .95, depthWrite: false, sizeAttenuation: true });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  points.matrixAutoUpdate = false;
  const nativeMatrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX);
  return { points, update(timeMs) {
    const active = activeCompartmentEvents(events, timeMs);
    active.forEach((event, i) => positions.set(maleCnsViewPosition(event.slice(3)), i * 3));
    geometry.setDrawRange(0, active.length); geometry.attributes.position.needsUpdate = true;
    return active.length;
  }, coordinateView(native) {
    if (native) points.matrix.copy(nativeMatrix); else points.matrix.identity();
    points.matrixWorldNeedsUpdate = true;
  }, dispose() { geometry.dispose(); material.dispose(); } };
}
