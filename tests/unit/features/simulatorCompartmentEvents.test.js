import { activeCompartmentEvents, createCompartmentEventLayer } from '../../../src/features/simulator/compartmentEvents';
import { contactToScene } from '../../../src/features/simulator/field/FieldContactScene';
import * as THREE from 'three';

jest.mock('three/examples/jsm/controls/OrbitControls.js', () => ({ OrbitControls: jest.fn() }));
jest.mock('three/examples/jsm/controls/TransformControls.js', () => ({ TransformControls: jest.fn() }));

const events = [['10', 1, 0, 10, 20, 30], ['20', 2, 1, 40, 50, 60]];

test('only displays actual sampled transitions in the current time window', () => {
  expect(activeCompartmentEvents(events, .5)).toEqual([]);
  expect(activeCompartmentEvents(events, 1.2)).toEqual([events[0]]);
  expect(activeCompartmentEvents(events, 1.9)).toEqual([]);
  expect(activeCompartmentEvents(events, 2)).toEqual([events[1]]);
});

test('draws saved native coordinates without drawing invented paths', () => {
  const layer = createCompartmentEventLayer({ events });
  layer.coordinateView(true);
  expect(layer.update(1.2)).toBe(1);
  expect(layer.points.geometry.drawRange.count).toBe(1);
  const positions = layer.points.geometry.attributes.position.array;
  const expected = contactToScene(events[0].slice(3)).toArray();
  const actual = new THREE.Vector3(...positions.slice(0, 3)).applyMatrix4(layer.points.matrix).toArray();
  for (let i = 0; i < 3; i += 1) expect(actual[i]).toBeCloseTo(expected[i], 6);
  expect(layer.update(1.9)).toBe(0);
  expect(layer.points.geometry.drawRange.count).toBe(0);
  layer.dispose();
});
