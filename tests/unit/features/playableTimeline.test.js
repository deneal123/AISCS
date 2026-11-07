import { playableTimeline } from '../../../src/features/simulator/recording/playableTimeline';

test('allows playback of network events without fabricating an electrode signal', () => {
  expect(playableTimeline({ networkOnly: true, time_ms: [0, 1, 2], signal_uv: null })).toBe(true);
  expect(playableTimeline({ time_ms: [0, 1, 2], signal_uv: null })).toBe(false);
  expect(playableTimeline({ networkOnly: true, time_ms: [0, 0], signal_uv: null })).toBe(false);
});

test('accepts only a finite, ordered recording with matching signal', () => {
  expect(playableTimeline({ time_ms: [0, 1], signal_uv: [0, .1] })).toBe(true);
  for (const value of [null, {}, { time_ms: undefined }, { time_ms: [0] },
    { time_ms: [0, 1] }, { time_ms: [0, 1], signal_uv: [0] },
    { time_ms: [0, NaN], signal_uv: [0, 0] },
    { time_ms: [0, 0], signal_uv: [0, 0] },
    { time_ms: [0, 1], signal_uv: [0, Infinity] }]) {
    expect(playableTimeline(value)).toBe(false);
  }
});
