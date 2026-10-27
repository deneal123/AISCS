import { smoothFlySurface } from '../../../src/features/simulator/flySurface';

test('display subdivision preserves its input and produces a finite surface inside its source bounds', () => {
  const triangle = [0, 0, 0, 1, 0, 0, 0, 1, 0], original = [...triangle];
  const result = smoothFlySurface(triangle);
  expect(triangle).toEqual(original);
  expect(result.indices).toHaveLength(12);
  expect(result.positions.every(Number.isFinite)).toBe(true);
  expect(result.positions.every(value => value >= 0 && value <= 1)).toBe(true);
  expect(result.indices.every(value => value < result.positions.length / 3)).toBe(true);
});

test('shared source vertices produce a connected display mesh, including open boundaries', () => {
  const square = [0,0,0, 1,0,0, 0,1,0, 1,0,0, 1,1,0, 0,1,0];
  const result = smoothFlySurface(square);
  expect(result.indices).toHaveLength(24);
  expect(result.positions).toHaveLength(9 * 3); // 4 original vertices and 5 shared edges
  expect(new Set(result.indices).size).toBe(9);
});
