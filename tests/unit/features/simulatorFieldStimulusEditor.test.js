import { normalizeFieldStimulus } from '../../../src/features/simulator/field/FieldStimulusEditor';

const base = { duration_ms: 10, dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3,
  rise_time_ms: .2, interphase_gap_ms: 0, pulse_shape: 'monophasic', conductivity_s_m: .3,
  clearance_um: 1, current_na: 1000, nseg_per_edge: 1 };

test('normalizes valid numeric input and checks independent phase timing', () => {
  expect(normalizeFieldStimulus({ ...base, current_na: '20' }, null).current_na).toBe(20);
  expect(normalizeFieldStimulus({ ...base, pulse_shape: 'biphasic', interphase_gap_ms: .5 }, null)).not.toBeNull();
  expect(normalizeFieldStimulus({ ...base, pulse_shape: 'biphasic', interphase_gap_ms: 7 }, null)).toBeNull();
  expect(normalizeFieldStimulus({ ...base, pulse_end_ms: 2 }, null)).toBeNull();
  expect(normalizeFieldStimulus({ ...base, dt_ms: .3 }, null)).toBeNull();
  expect(normalizeFieldStimulus({ ...base, nseg_per_edge: 2 }, null)).toBeNull();
  expect(normalizeFieldStimulus(base, { high_hz: 10000 })).toBeNull();
});

test('validates a pulse train and preserves the legacy single-pulse contract', () => {
  const single = normalizeFieldStimulus({ ...base, pulse_count: '1', pulse_interval_ms: '5' }, null);
  expect(single).not.toHaveProperty('pulse_count');
  expect(single).not.toHaveProperty('pulse_interval_ms');
  const train = normalizeFieldStimulus({ ...base, pulse_count: '2', pulse_interval_ms: '5' }, null);
  expect(train.pulse_count).toBe(2);
  expect(train.pulse_interval_ms).toBe(5);
  expect(normalizeFieldStimulus({ ...base, pulse_count: 2 }, null)).toBeNull();
  expect(normalizeFieldStimulus({ ...base, pulse_count: 2, pulse_interval_ms: 1 }, null)).toBeNull();
  expect(normalizeFieldStimulus({ ...base, pulse_count: 3, pulse_interval_ms: 5 }, null)).toBeNull();
});
