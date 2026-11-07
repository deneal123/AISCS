import * as THREE from 'three';
import { snapFieldContactToNeuropil } from '../../../src/features/simulator/field/fieldNeuropilSnap';
import { maleCnsNativePosition, maleCnsViewPosition } from '../../../src/features/simulator/connectome/connectomeMorphology';

test('snaps to the nearest region surface and returns the same native frame', () => {
  const regions = new THREE.Group();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial());
  mesh.position.set(2, 0, 0); mesh.userData.region = 'region-a'; regions.add(mesh);
  const other = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial());
  other.position.set(-2, 0, 0); other.userData.region = 'region-b'; regions.add(other);
  const point = [3, 0.1, 0.2];
  const result = snapFieldContactToNeuropil(maleCnsNativePosition(point), regions);
  const actual = maleCnsViewPosition(result.coordinates);
  expect(actual[0]).toBeCloseTo(2.5, 4); expect(actual[1]).toBeCloseTo(0.1, 4);
  const nativeDelta = new THREE.Vector3(...result.coordinates).sub(new THREE.Vector3(...maleCnsNativePosition(point)));
  const tangent = new THREE.Vector3(...maleCnsNativePosition([2.5, .1, .3]))
    .sub(new THREE.Vector3(...maleCnsNativePosition([2.5, .1, .2]))).normalize();
  expect(Math.abs(nativeDelta.dot(tangent))).toBeLessThan(.002);
  expect(result.region).toBe('region-a'); expect(new THREE.Vector3(...result.normal).length()).toBeCloseTo(1);
  mesh.geometry.dispose(); mesh.material.dispose(); other.geometry.dispose(); other.material.dispose();
});

test('rejects missing region surfaces', () => {
  expect(() => snapFieldContactToNeuropil([1, 2, 3], new THREE.Group())).toThrow('neuropil_surface_unavailable');
});

test('chooses the physically nearest native-EM surface when body-view scaling changes visual distance', () => {
  const regions = new THREE.Group();
  const add = (name, points) => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(points.flatMap(maleCnsViewPosition), 3));
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
    mesh.userData.region = name; regions.add(mesh);
    return mesh;
  };
  // X-native is 90 µm away and Z-native is 80 µm away, but the body
  // projection stretches Z so the X-native triangle looks closer on screen.
  const x = add('visually-nearer', [[483, 196, 176], [483, 204, 176], [483, 200, 184]]);
  const z = add('physically-nearer', [[389, 196, 260], [397, 196, 260], [393, 204, 260]]);
  const result = snapFieldContactToNeuropil([393, 200, 180], regions);
  expect(result.region).toBe('physically-nearer');
  expect(result.coordinates[0]).toBeCloseTo(393, 2);
  expect(result.coordinates[1]).toBeCloseTo(200, 2);
  expect(result.coordinates[2]).toBeCloseTo(260, 2);
  for (const mesh of [x, z]) { mesh.geometry.dispose(); mesh.material.dispose(); }
});
