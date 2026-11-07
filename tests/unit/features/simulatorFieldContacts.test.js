import * as THREE from 'three';
import { createFieldContactLayer } from '../../../src/features/simulator/field/fieldContacts';
import { maleCnsViewPosition, NATIVE_VIEW_MATRIX } from '../../../src/features/simulator/connectome/connectomeMorphology';
import { snapFieldContactToBody } from '../../../src/features/simulator/field/fieldSurfaceSnap';

const simulation = { source_um: [429, 328, 228], return_um: [929, 328, 228],
  electrode_um: [419, 319, 360], reference_um: [919, 319, 360] };

test('keeps all four contacts in the same body and native frames as the graph', () => {
  const layer = createFieldContactLayer(simulation);
  expect(layer.group.children.map(child => child.name)).toEqual(['STIM+', 'STIM−', 'E1', 'REF']);
  layer.group.children.forEach(contact => {
    expect(contact.getObjectByName('probe-shaft')).toBeTruthy();
    expect(contact.getObjectByName('contact-tip')).toBeTruthy();
  });
  layer.coordinateView(false);
  layer.group.updateMatrixWorld(true);
  layer.group.children.forEach((marker, i) => {
    const raw = Object.values(simulation)[i];
    expect(marker.getWorldPosition(new THREE.Vector3()).toArray()).toEqual(maleCnsViewPosition(raw));
  });
  layer.coordinateView(true);
  layer.group.updateMatrixWorld(true);
  layer.group.children.forEach((marker, i) => {
    const raw = Object.values(simulation)[i];
    const expected = new THREE.Vector3(...maleCnsViewPosition(raw)).applyMatrix4(new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX));
    expect(marker.getWorldPosition(new THREE.Vector3()).distanceTo(expected)).toBeLessThan(1e-12);
  });
  layer.dispose();
});

test('rejects missing or nonfinite physical coordinates', () => {
  expect(() => createFieldContactLayer({ ...simulation, source_um: [0, NaN, 0] })).toThrow('invalid_field_contact');
  expect(() => createFieldContactLayer({ ...simulation, reference_um: null })).toThrow('invalid_field_contact');
});

test('hover and selected outlines follow their contacts without changing coordinates', () => {
  const layer = createFieldContactLayer(simulation);
  const positions = layer.group.children.map(marker => marker.position.toArray());
  layer.setHighlight('source_um', 'reference_um');
  expect(layer.group.children[0].getObjectByName('probe-hover-outline').visible).toBe(true);
  expect(layer.group.children[3].getObjectByName('probe-selected-outline').visible).toBe(true);
  expect(layer.group.children[0].getObjectByName('probe-selected-outline').visible).toBe(false);
  layer.setHighlight('source_um', 'source_um');
  expect(layer.group.children[0].getObjectByName('probe-hover-outline').visible).toBe(false);
  expect(layer.group.children[0].getObjectByName('probe-selected-outline').visible).toBe(true);
  expect(layer.group.children.map(marker => marker.position.toArray())).toEqual(positions);
  layer.dispose();
});

test('projects proposed native contact onto the body surface with an external offset', () => {
  const body = new THREE.Group(), geometry = new THREE.BoxGeometry(1, 1, 1);
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
  mesh.name = 'thorax'; mesh.userData.sourceGeometry = geometry; body.add(mesh);
  const result = snapFieldContactToBody([393, 200, 180], body);
  const point = new THREE.Vector3(...maleCnsViewPosition(result.coordinates));
  expect(Math.max(Math.abs(point.x), Math.abs(point.y), Math.abs(point.z))).toBeCloseTo(.525, 3);
  expect(new THREE.Vector3(...result.normal).length()).toBeCloseTo(1);
  geometry.dispose(); mesh.material.dispose();
});

test('corrects an inward surface normal when the closed mesh winding is reversed', () => {
  const body = new THREE.Group(), geometry = new THREE.BoxGeometry(1, 1, 1), index = geometry.index;
  for (let i = 0; i < index.count; i += 3) {
    const second = index.getX(i + 1); index.setX(i + 1, index.getX(i + 2)); index.setX(i + 2, second);
  }
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
  mesh.name = 'thorax'; mesh.userData.sourceGeometry = geometry; body.add(mesh);
  const result = snapFieldContactToBody([393, 200, 180], body);
  const point = new THREE.Vector3(...maleCnsViewPosition(result.coordinates));
  expect(Math.max(Math.abs(point.x), Math.abs(point.y), Math.abs(point.z))).toBeCloseTo(.525, 3);
  geometry.dispose(); mesh.material.dispose();
});
