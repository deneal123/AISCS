import { fieldCellActive } from '../../../src/features/simulator/field/FieldNetworkScene';

jest.mock('three/examples/jsm/controls/OrbitControls.js', () => ({}));
jest.mock('three/examples/jsm/controls/TransformControls.js', () => ({}));

test('the arbor is highlighted only around recorded cell events, including rewind', () => {
  expect(fieldCellActive([3, 12], 2.9)).toBe(false);
  expect(fieldCellActive([3, 12], 3)).toBe(true);
  expect(fieldCellActive([3, 12], 8.9)).toBe(true);
  expect(fieldCellActive([3, 12], 9)).toBe(false);
  expect(fieldCellActive([3, 12], 12)).toBe(true);
  expect(fieldCellActive([3, 12], 0)).toBe(false);
});
