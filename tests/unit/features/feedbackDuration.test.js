import { validFeedbackDuration } from '../../../src/features/simulator/feedbackDuration';

const simulation = { dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3, rise_time_ms: .2,
  interphase_gap_ms: 0, pulse_shape: 'monophasic' };

test('accepts a bounded integer duration only when the full pulse fits the physical grid', () => {
  expect(validFeedbackDuration(simulation, 10)).toBe(true);
  expect(validFeedbackDuration(simulation, 50)).toBe(true);
  for (const value of ['', 3, 10.5, 1001]) expect(validFeedbackDuration(simulation, value)).toBe(false);
  expect(validFeedbackDuration({ ...simulation, dt_ms: .3 }, 10)).toBe(false);
});

test('requires the whole biphasic pulse train within the observation window', () => {
  const train = { ...simulation, pulse_shape: 'biphasic', interphase_gap_ms: .5,
    pulse_count: 2, pulse_interval_ms: 4 };
  expect(validFeedbackDuration(train, 8)).toBe(false);
  expect(validFeedbackDuration(train, 9)).toBe(true);
  expect(validFeedbackDuration({ ...train, pulse_interval_ms: 2 }, 10)).toBe(false);
});
