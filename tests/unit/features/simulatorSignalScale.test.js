import { signalAxisLabel, signalHalfRange } from '../../../src/features/simulator/recording/signalScale';

test('keeps a weak signal visible without changing its physical amplitude', () => {
  expect(signalHalfRange([0, 4.27e-7, -2e-7])).toBe(4.27e-7);
  expect(signalAxisLabel(4.27e-7)).toBe('4.3e-7');
  expect(signalAxisLabel(-4.27e-7)).toBe('-4.3e-7');
});

test('uses a common scale for comparison and a stable zero fallback', () => {
  expect(signalHalfRange([1e-7], [-3e-7])).toBe(3e-7);
  expect(signalHalfRange([0], [0])).toBe(0.1);
  expect(signalAxisLabel(0)).toBe('0');
});
