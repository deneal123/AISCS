import { BoxGeometry, BufferGeometry, Float32BufferAttribute, Mesh } from 'three';
import { surfaceContactPosition, surfaceContactNormal, surfaceContactLocation, SURFACE_CONTACT_OFFSET_UM } from '../../../src/features/simulator/scene/surfacePlacement';

test('internal recording coordinates are detected independently of distance to the surface', () => {
  const mesh = new Mesh(), source = new BoxGeometry(2, 2, 2);
  mesh.userData.sourceGeometry = source;
  mesh.position.set(1, 2, 3); mesh.rotation.z = .3;
  expect(surfaceContactLocation([1, 2, 3], mesh)).toBe('inside');
  expect(surfaceContactLocation([5, 2, 3], mesh)).toBe('outside');
  expect(surfaceContactLocation([NaN, 2, 3], mesh)).toBe('unknown');
  expect(surfaceContactLocation([1, 2], mesh)).toBe('unknown');
  source.dispose(); mesh.geometry.dispose(); mesh.material.dispose();
});

test('surface contact uses the registered origin, millimetres and a normalized outward offset', () => {
  const origin = [1, 2, 3], point = [1.1, 2.2, 3.3];
  const contact = surfaceContactPosition(point, [0, 0, 4], origin);
  expect(contact.x_um).toBeCloseTo(100);
  expect(contact.y_um).toBeCloseTo(200);
  expect(contact.z_um).toBeCloseTo(300 + SURFACE_CONTACT_OFFSET_UM);
  const offset = surfaceContactPosition(origin, [1, -2, 2], origin);
  expect(Math.hypot(...Object.values(offset))).toBeCloseTo(25);
  expect(offset.y_um).toBeLessThan(0);
});

test('shaft alignment uses source triangles, world transforms and an outside-only proximity test', () => {
  const source = new BufferGeometry();
  source.setAttribute('position', new Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
  const mesh = new Mesh(); mesh.userData.sourceGeometry = source;
  mesh.position.set(1, 2, 3); mesh.rotation.x = Math.PI / 2; mesh.updateMatrixWorld();
  const normal = surfaceContactNormal([1.2, 1.975, 3.2], mesh);
  expect(normal.x).toBeCloseTo(0); expect(normal.y).toBeCloseTo(-1); expect(normal.z).toBeCloseTo(0);
  expect(surfaceContactNormal([1.2, 2.025, 3.2], mesh)).toBeNull();
  expect(surfaceContactNormal([1.2, 1.8, 3.2], mesh)).toBeNull();
  source.dispose(); mesh.geometry.dispose(); mesh.material.dispose();
});

test('unsupported coordinates and normals are rejected without clamping', () => {
  expect(() => surfaceContactPosition([.49, 0, 0], [1, 0, 0], [0, 0, 0])).toThrow('domain');
  expect(() => surfaceContactPosition([0, 0, 0], [0, 0, 0], [0, 0, 0])).toThrow('normal');
  for (const invalid of [[NaN, 0, 0], [Infinity, 0, 0], [0, 0], ['0', 0, 0]]) {
    expect(() => surfaceContactPosition(invalid, [0, 0, 1], [0, 0, 0])).toThrow('geometry');
  }
});
