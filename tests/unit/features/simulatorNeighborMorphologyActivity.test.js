import { neighborIsActive } from '../../../src/features/simulator/connectome/neighborMorphologyActivity';

test('highlights only the recorded event window and clears on rewind', () => {
  expect(neighborIsActive(9, 10)).toBe(false);
  expect(neighborIsActive(10, 10)).toBe(true);
  expect(neighborIsActive(15.9, 10)).toBe(true);
  expect(neighborIsActive(16, 10)).toBe(false);
  expect(neighborIsActive(10, null)).toBe(false);
});
