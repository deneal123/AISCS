// Exact annotated nerve populations. Display corridors are schematic; no
// propagation delay or muscle action is inferred from their drawn length.
export const PERIPHERAL_REGIONS = ['front_left', 'front_right', 'middle_left', 'middle_right', 'hind_left', 'hind_right', 'abdomen', 'head'];
const SOURCE = 'd27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee';
const DIGEST = '5e40a6a229a3b6dd19546d6b8c3306145f5a1605a01ef092b32780cf6dacbc21';

export function buildPeripheralReadout(manifest, data) {
  if (manifest.version !== 'male-cns-peripheral-readout-v1' || manifest.dataset_id !== data.description.dataset_id
    || manifest.annotations_sha256 !== SOURCE || data.description.annotations_sha256 !== SOURCE
    || manifest.count !== 10446 || manifest.rows?.length !== manifest.count) throw new Error('peripheral_identity');
  const channels = new Int8Array(data.node_ids.length).fill(-1), counts = {}, events = Array.from({ length: 16 }, () => []);
  let previous = 0n, index = 0;
  for (const [id, region, role] of manifest.rows) {
    const bodyId = BigInt(id), group = PERIPHERAL_REGIONS.indexOf(region);
    if (bodyId <= previous || group < 0 || !['sensory', 'motor'].includes(role)) throw new Error('peripheral_population');
    while (index < data.node_ids.length && data.node_ids[index] < bodyId) index += 1;
    if (data.node_ids[index] !== bodyId) throw new Error('peripheral_node');
    previous = bodyId; channels[index] = group * 2 + (role === 'motor' ? 1 : 0);
    const key = region + ':' + role; counts[key] = (counts[key] || 0) + 1;
  }
  if (Object.keys(counts).length !== 16 || Object.entries(counts).some(([key, count]) => manifest.counts[key] !== count)) throw new Error('peripheral_coverage');
  data.spike_neurons.forEach((node, event) => { if (channels[node] >= 0) events[channels[node]].push(data.spike_times_ms[event]); });
  return { events, counts, cells: manifest.count };
}

export async function loadPeripheralReadout(data, signal) {
  const response = await fetch('/assets/simulator/malecns/peripheral.json', { signal });
  if (!response.ok) throw new Error('peripheral_unavailable');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== 619524) throw new Error('peripheral_size');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (digest !== DIGEST) throw new Error('peripheral_integrity');
  return buildPeripheralReadout(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), data);
}

function upperBound(times, value) {
  let low = 0, high = times.length;
  while (low < high) { const mid = (low + high) >>> 1; if (times[mid] <= value) low = mid + 1; else high = mid; }
  return low;
}

export function peripheralCountsAtTime(readout, region, timeMs) {
  const index = PERIPHERAL_REGIONS.indexOf(region);
  if (!readout || index < 0 || !Number.isFinite(timeMs)) return [0, 0];
  return [0, 1].map(role => {
    const times = readout.events[index * 2 + role];
    return upperBound(times, timeMs) - upperBound(times, timeMs - 6);
  });
}
