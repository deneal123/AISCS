// Exact source IDs and saved LIF events own this conditional display cue.
// This is not a muscle model: soma-side grouping does not prove target laterality.
export const MOTOR_REGIONS = ['front_left', 'front_right', 'middle_left', 'middle_right', 'hind_left', 'hind_right'];
export const MOTOR_VERSION = 'male-cns-motor-display-v1';
const COUNTS = [41, 40, 58, 58, 62, 60];
const SHA256 = '622e95da2d5af6c87d34fa6bb4b6c2c52e5a119c8d5f0c84f4535cca6572997f';
const ANNOTATIONS = 'd27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee';

export function buildMotorReadout(manifest, data) {
  if (manifest.version !== MOTOR_VERSION || manifest.dataset_id !== data.description.dataset_id
    || manifest.annotations_sha256 !== ANNOTATIONS || manifest.annotations_sha256 !== data.description.annotations_sha256
    || manifest.neurons !== 319 || manifest.cells?.length !== 319) throw new Error('motor_identity');
  const indices = new Map(Array.from(data.node_ids, (id, index) => [id.toString(), index]));
  const population = new Map(), counts = new Uint32Array(6);
  for (const cell of manifest.cells) {
    const region = MOTOR_REGIONS.indexOf(cell.region), index = indices.get(cell.id);
    const segment = region < 2 ? 'T1' : region < 4 ? 'T2' : 'T3';
    const nerve = region < 2 ? 'ProLN' : region < 4 ? 'MesoLN' : 'MetaLN';
    if (region < 0 || index === undefined || population.has(index) || cell.neuromere !== segment
      || cell.exit_nerve !== nerve || cell.soma_side !== (region % 2 ? 'R' : 'L')) throw new Error('motor_population');
    population.set(index, region); counts[region] += 1;
  }
  if (!counts.every((count, region) => count === COUNTS[region] && manifest.counts[MOTOR_REGIONS[region]] === count)) throw new Error('motor_coverage');
  const events = MOTOR_REGIONS.map(() => []), active = new Set();
  data.spike_neurons.forEach((index, event) => {
    const region = population.get(index);
    if (region !== undefined) { events[region].push(data.spike_times_ms[event]); active.add(index); }
  });
  return { version: MOTOR_VERSION, events, active: active.size,
    first: Math.min(...events.map(times => times[0] ?? Infinity)),
    source: data, laterality: 'soma-side-display-only' };
}

export async function loadMotorReadout(data, signal) {
  const response = await fetch('/assets/simulator/malecns/motor.json', { signal });
  if (!response.ok) throw new Error('motor_unavailable');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== 56797) throw new Error('motor_size');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (digest !== SHA256) throw new Error('motor_integrity');
  return buildMotorReadout(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), data);
}

export function motorAngleAtTime(readout, region, timeMs) {
  const times = readout?.events[MOTOR_REGIONS.indexOf(region)];
  if (!times || !Number.isFinite(timeMs)) return 0;
  // Display constants, not fitted or claimed biophysical muscle parameters.
  let low = 0, high = times.length;
  while (low < high) { const mid = (low + high) >>> 1; if (times[mid] <= timeMs) low = mid + 1; else high = mid; }
  let activity = 0;
  for (let i = low - 1; i >= 0 && timeMs - times[i] < 24; i -= 1) activity += Math.exp(-(timeMs - times[i]) / 8);
  return Math.min(1, activity / 3) * .25;
}

export const motorMaximumAtTime = (readout, timeMs) => Math.max(...MOTOR_REGIONS.map(region => motorAngleAtTime(readout, region, timeMs)));

export function causalOnsets(data, readout) {
  if (!data) return null;
  const inputs = new Set(data.input_indices);
  let input = null, network = null;
  for (let event = 0; event < data.spike_neurons.length; event += 1) {
    if (inputs.has(data.spike_neurons[event])) { if (input === null) input = data.spike_times_ms[event]; }
    else if (network === null) network = data.spike_times_ms[event];
    if (input !== null && network !== null) break;
  }
  return { input, network, motor: Number.isFinite(readout?.first) ? readout.first : null };
}
