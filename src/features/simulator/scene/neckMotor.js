const SOURCE = 'd27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee';
const DIGEST = 'd54f14c9e4608335da0a7210bcf49dc6d5c16d8387b141b229f6d043c14551c9';

export function buildNeckMotorReadout(manifest, data) {
  if (manifest.version !== 'male-cns-cvn-motor-v1' || manifest.dataset_id !== data.description.dataset_id
      || manifest.annotations_sha256 !== SOURCE || data.description.annotations_sha256 !== SOURCE
      || manifest.nerve !== 'CvN' || manifest.cells?.length !== 24
      || manifest.counts?.cb_motor !== 20 || manifest.counts?.vnc_motor !== 4) throw new Error('neck_identity');
  const indices = new Map(Array.from(data.node_ids, (id, i) => [id.toString(), i]));
  const selected = new Set(), counts = { cb_motor: 0, vnc_motor: 0 };
  let previous = 0n;
  for (const cell of manifest.cells) {
    const id = BigInt(cell.id), index = indices.get(cell.id);
    if (id <= previous || index === undefined || !(cell.superclass in counts)) throw new Error('neck_population');
    selected.add(index); counts[cell.superclass] += 1; previous = id;
  }
  if (counts.cb_motor !== 20 || counts.vnc_motor !== 4) throw new Error('neck_coverage');
  const times = [], active = new Set();
  data.spike_neurons.forEach((index, event) => {
    if (selected.has(index)) { times.push(data.spike_times_ms[event]); active.add(index); }
  });
  return { times, active: active.size, first: times[0] ?? null };
}

export async function loadNeckMotorReadout(data, signal) {
  const response = await fetch('/assets/simulator/malecns/neck-motor.json', { signal });
  if (!response.ok) throw new Error('neck_unavailable');
  const bytes = await response.arrayBuffer();
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
  if (digest !== DIGEST) throw new Error('neck_integrity');
  return buildNeckMotorReadout(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), data);
}

export function neckEventsAtTime(readout, time) {
  if (!readout || !Number.isFinite(time)) return 0;
  return readout.times.reduce((count, t) => count + Number(t <= time && t > time - 6), 0);
}
