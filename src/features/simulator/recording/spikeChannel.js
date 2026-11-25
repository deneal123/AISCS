// The electrode trace is a field sum, not a firing record: a pass that fires
// hundreds of spikes publishes a membrane potential that is back at rest by the
// end of the window (H67, H82, H117). The spike count is the second channel of
// the same recording and is published beside it, never derived from the trace.
export const SPIKE_CHANNEL_VERSION = 'malecns-spike-channel-v1';

export const SPIKE_CHANNEL_PHASES = Object.freeze([
  ['initial_active', 'Первый проход'],
  ['control', 'Контроль'],
  ['converged_active', 'Связанный проход'],
]);

function count(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

// Returns null when the run does not publish spike counts, so an older artifact
// stays "not measured" instead of becoming a measured zero.
export function spikeChannelReadout(run) {
  const preview = run?.result?.preview;
  const spikes = preview?.spikes;
  if (!spikes || preview?.kind !== 'experimental-full-population-feedback') return null;
  const phases = SPIKE_CHANNEL_PHASES.map(([key, label]) => ({ key, label, spikes: count(spikes[key]) }));
  if (phases.some(phase => phase.spikes === null)) return null;
  const total = phases.reduce((sum, phase) => sum + phase.spikes, 0);
  return { version: SPIKE_CHANNEL_VERSION, available: true, total, phases,
    channel: typeof spikes.channel === 'string' ? spikes.channel : 'signals.npz',
    note: 'пороговые переходы целых клеток на миллисекунду сетки; ' +
      'запись E1−REF — сумма поля и может читаться как ноль, пока клетки работают' };
}

// One line for the recording panel; null keeps the panel silent rather than
// claiming a channel the artifact does not carry.
export function spikeChannelSentence(run) {
  const readout = spikeChannelReadout(run);
  if (!readout) return null;
  const parts = readout.phases.map(phase => `${phase.label.toLowerCase()}: ${phase.spikes.toLocaleString('ru-RU')}`);
  return `Второй канал записи — счётчик спайков, всего ${readout.total.toLocaleString('ru-RU')} (${parts.join('; ')}). Запись E1−REF остаётся суммой поля.`;
}
