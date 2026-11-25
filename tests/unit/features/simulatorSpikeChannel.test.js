import { spikeChannelReadout, spikeChannelSentence, SPIKE_CHANNEL_VERSION } from '../../../src/features/simulator/recording/spikeChannel';

function run(spikes, kind = 'experimental-full-population-feedback') {
  return { result: { manifest: { kind }, preview: { kind, spikes } } };
}

const measured = { initial_active: 4, control: 0, converged_active: 589, channel: 'signals.npz' };

test('counts every pass of a converged full-population run', () => {
  const readout = spikeChannelReadout(run(measured));
  expect(readout.version).toBe(SPIKE_CHANNEL_VERSION);
  expect(readout.total).toBe(593);
  expect(readout.phases.map(phase => phase.spikes)).toEqual([4, 0, 589]);
});

test('a run without the channel stays unmeasured instead of reading as zero', () => {
  expect(spikeChannelReadout(run(undefined))).toBeNull();
  expect(spikeChannelReadout(run({ initial_active: 0, control: 0 }))).toBeNull();
  expect(spikeChannelSentence(run(undefined))).toBeNull();
});

test('a damaged count is not silently replaced', () => {
  expect(spikeChannelReadout(run({ ...measured, converged_active: -1 }))).toBeNull();
  expect(spikeChannelReadout(run({ ...measured, converged_active: 1.5 }))).toBeNull();
});

test('the sentence names the count and keeps the electrode trace separate', () => {
  const sentence = spikeChannelSentence(run(measured));
  expect(sentence).toContain('593');
  expect(sentence).toContain('суммой поля');
});

test('another experiment kind is not described as a full-population recording', () => {
  expect(spikeChannelReadout(run(measured, 'experimental-field-proxy'))).toBeNull();
});
