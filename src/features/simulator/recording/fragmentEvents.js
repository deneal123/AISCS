const canonical = value => Array.isArray(value) ? value.map(canonical)
  : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;

export function applyFragmentEvents(base, buffer, metadata, configuration) {
  const n = base?.node_ids?.length, event = metadata?.events;
  if (!n || metadata?.configuration?.graph_manifest_sha256 !== base.description?.manifest_sha256
      || configuration?.graph_manifest_sha256 !== base.description.manifest_sha256
      || JSON.stringify(canonical(metadata.configuration)) !== JSON.stringify(canonical(configuration))
      || event?.format !== 'fragment-events-v1' || event.graph_sha256 !== configuration.graph_manifest_sha256
      || event.node_count !== n || !Number.isSafeInteger(event.event_count) || event.event_count < 0
      || buffer.byteLength !== n * 8 + event.event_count * 8
      || !Array.isArray(configuration.source_ids) || !configuration.source_ids.length) throw new Error('fragment_identity');
  const ids = new BigUint64Array(buffer, 0, n);
  if (!ids.every((value, i) => value === base.node_ids[i])) throw new Error('fragment_nodes');
  const indices = new Int32Array(buffer, n * 8, event.event_count);
  const times = new Float32Array(buffer, n * 8 + event.event_count * 4, event.event_count);
  const sourceIds = configuration.source_ids;
  if (sourceIds.some(value => !Number.isSafeInteger(value) || value <= 0)
      || new Set(sourceIds).size !== sourceIds.length) throw new Error('fragment_sources');
  const sourceSet = new Set(sourceIds.map(String)), input = [];
  ids.forEach((id, index) => { if (sourceSet.has(String(id))) input.push(index); });
  if (input.length !== sourceIds.length) throw new Error('fragment_sources');
  const sourceMask = new Uint8Array(n); input.forEach(index => { sourceMask[index] = 1; });
  const counts = new Int32Array(n), duration = configuration.simulation?.duration_ms;
  if (!Number.isInteger(duration) || duration < 1 || duration > 1000) throw new Error('fragment_duration');
  indices.forEach((index, i) => {
    if (index < 0 || index >= n || sourceMask[index] || !Number.isInteger(times[i]) || times[i] <= 0
        || times[i] > duration || (i && times[i] < times[i - 1])) throw new Error('fragment_events');
    counts[index] += 1;
  });
  return { ...base, spike_neurons: indices, spike_times_ms: times, counts, input_indices: Int32Array.from(input),
    description: { ...base.description, duration_ms: duration, spikes: indices.length, input_neurons: input.length,
      active_neurons: counts.reduce((sum, count) => sum + Number(count > 0), 0),
      spikes_outside_input_population: indices.length, stimulus_region: 'electrical',
      interpretation: 'experimental one-way fragment edge events; source cells are silenced' } };
}

export async function verifyFragmentEvents(base, eventBuffer, eventArtifact, metadataBuffer, metadataArtifact, configuration) {
  async function verify(buffer, artifact) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== artifact?.bytes || !/^[a-f0-9]{64}$/.test(artifact?.sha256 || '')) throw new Error('fragment_size');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (digest !== artifact.sha256) throw new Error('fragment_checksum');
  }
  await Promise.all([verify(eventBuffer, eventArtifact), verify(metadataBuffer, metadataArtifact)]);
  const metadata = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(metadataBuffer));
  return applyFragmentEvents(base, eventBuffer, metadata, configuration);
}

export async function verifyCoupledEvents(base, buffer, artifact, run) {
  const preview = run?.result?.preview, manifest = run?.result?.manifest;
  const graphHash = run?.configuration?.graph_manifest_sha256;
  const entry = manifest?.files?.find(file => file.name === 'coupled-events.bin');
  if (!(buffer instanceof ArrayBuffer) || artifact?.name !== 'coupled-events.bin'
      || buffer.byteLength !== artifact.bytes || entry?.bytes !== artifact.bytes
      || !/^[a-f0-9]{64}$/.test(artifact?.sha256 || '') || entry?.sha256 !== artifact.sha256
      || manifest?.kind !== 'experimental-coupled-population'
      || manifest.configuration_sha256 !== run?.configuration_sha256
      || manifest.graph_sha256 !== graphHash || preview?.graph_sha256 !== graphHash
      || base?.description?.manifest_sha256 !== graphHash
      || !['converged', 'converged_partial'].includes(preview?.status)
      || !Number.isSafeInteger(preview?.network_spikes) || preview.network_spikes < 0
      || preview.graph_cells !== base?.node_ids?.length
      || preview.source_cells !== preview.source_ids?.length) throw new Error('coupled_identity');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))]
    .map(byte => byte.toString(16).padStart(2, '0')).join('');
  if (digest !== artifact.sha256) throw new Error('coupled_checksum');
  const configuration = { graph_manifest_sha256: graphHash, source_ids: preview.source_ids,
    simulation: { duration_ms: preview.duration_ms } };
  const metadata = { configuration, events: { format: 'fragment-events-v1', graph_sha256: graphHash,
    node_count: preview.graph_cells, event_count: preview.network_spikes } };
  const data = applyFragmentEvents(base, buffer, metadata, configuration);
  return { ...data, description: { ...data.description,
    interpretation: 'experimental coupled population and uncalibrated LIF network' } };
}

// A marker denotes a threshold crossing in at least one source segment; it is
// not a whole-neuron spike and must not drive the network edge animation.
export async function verifyCoupledSourceEvents(base, buffer, artifact, run) {
  const manifest = run?.result?.manifest, preview = run?.result?.preview;
  const entry = manifest?.files?.find(file => file.name === 'coupled-source-events.bin');
  if (!(buffer instanceof ArrayBuffer) || artifact?.name !== 'coupled-source-events.bin'
      || buffer.byteLength !== artifact.bytes || entry?.bytes !== artifact.bytes
      || entry?.sha256 !== artifact.sha256 || !/^[a-f0-9]{64}$/.test(artifact.sha256 || '')
      || buffer.byteLength < 80) throw new Error('source_events_identity');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))]
    .map(byte => byte.toString(16).padStart(2, '0')).join('');
  if (digest !== artifact.sha256) throw new Error('source_events_checksum');
  const bytes = new Uint8Array(buffer), view = new DataView(buffer);
  const hex = (start, end) => [...bytes.subarray(start, end)].map(b => b.toString(16).padStart(2, '0')).join('');
  const nodes = view.getUint32(4, true), duration = view.getUint32(8, true), count = view.getUint32(12, true);
  if (String.fromCharCode(...bytes.subarray(0, 4)) !== 'SRC1'
      || nodes !== base.node_ids.length || nodes !== preview?.graph_cells
      || duration !== preview?.duration_ms || hex(16, 48) !== manifest.graph_sha256
      || hex(48, 80) !== manifest.configuration_sha256 || manifest.configuration_sha256 !== run.configuration_sha256
      || count > preview.source_cells * duration || buffer.byteLength !== 80 + count * 8) throw new Error('source_events_header');
  const indices = new Uint32Array(buffer, 80, count), times = new Uint32Array(buffer, 80 + count * 4, count);
  const sourceIndices = new Set(base.input_indices);
  indices.forEach((index, i) => {
    if (!sourceIndices.has(index) || times[i] < 1 || times[i] > duration
        || (i > 0 && (times[i] < times[i - 1] || (times[i] === times[i - 1] && index <= indices[i - 1])))) {
      throw new Error('source_events_order');
    }
  });
  return { ...base, physical_source_indices: indices, physical_source_times_ms: times };
}
