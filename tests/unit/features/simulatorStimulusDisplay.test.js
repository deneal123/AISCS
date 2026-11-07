import { stimulusDisplay } from '../../../src/features/simulator/recording/stimulusDisplay';

test('direct network means occupy complete millisecond intervals without linear interpolation', () => {
  const preview = { networkOnly: true, time_ms: [0, 1, 2, 3], stimulus_current_na: -300,
    stimulus_time_ms: [.5, 1.5, 2.5], stimulus_fraction: [0, .75, -.25] };
  expect(stimulusDisplay(preview)).toEqual({ current: -300,
    times: [0, 1, 1, 2, 2, 3], fractions: [0, 0, .75, .75, -.25, -.25] });
});

test('detailed stimulus samples retain their own time grid and values', () => {
  const times = [0, .2, 1, 2], fractions = [0, 1, .5, 0];
  const actual = stimulusDisplay({ electrical: true, stimulus_current_na: -100,
    stimulus_time_ms: times, stimulus_fraction: fractions });
  expect(actual).toEqual({ current: -100, times, fractions });
  expect(actual.times).toBe(times);
});

test('rejects inconsistent intervals, absent currents and nonfinite samples', () => {
  const preview = { networkOnly: true, time_ms: [0, 1, 2], stimulus_current_na: 0,
    stimulus_time_ms: [.5, 1.5], stimulus_fraction: [0, 0] };
  expect(stimulusDisplay(preview).current).toBe(0);
  expect(stimulusDisplay({ ...preview, stimulus_current_na: null })).toBeNull();
  expect(stimulusDisplay({ ...preview, stimulus_fraction: [0, NaN] })).toBeNull();
  expect(stimulusDisplay({ ...preview, time_ms: [0, .5, 2] })).toBeNull();
  expect(stimulusDisplay({ ...preview, stimulus_time_ms: [.5, 1.4] })).toBeNull();
  expect(stimulusDisplay({ ...preview, stimulus_fraction: [] })).toBeNull();
});
