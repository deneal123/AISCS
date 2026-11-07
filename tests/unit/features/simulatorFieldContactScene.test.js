import * as THREE from 'three';
import { contactToScene, draggedContactKey, sceneToContact } from '../../../src/features/simulator/field/FieldContactScene';

jest.mock('three/examples/jsm/controls/OrbitControls.js', () => ({}));
jest.mock('three/examples/jsm/controls/TransformControls.js', () => ({}));

test('native EM coordinates round trip through the visual orientation', () => {
  for (const point of [[393, 200, 180], [420, 175, 350], [-100, 2200, 0]]) {
    const result = sceneToContact(contactToScene(point));
    result.forEach((value, index) => expect(value).toBeCloseTo(point[index], 8));
  }
  expect(contactToScene([393, 200, 180])).toBeInstanceOf(THREE.Vector3);
});

test('a selection change cannot write the dragged marker to a different contact', () => {
  const stim = {}, ref = {}, markers = { source_um: stim, reference_um: ref };
  expect(draggedContactKey(markers, stim, 'source_um')).toBe('source_um');
  expect(draggedContactKey(markers, stim, 'reference_um')).toBeNull();
  expect(draggedContactKey(markers, null, 'source_um')).toBeNull();
  expect(draggedContactKey(markers, ref, 'unknown')).toBeNull();
});
