// Decode the independently saved field-driven event journal against the
// already verified scene graph. No activity from the scene run is retained.
const canonical = value => Array.isArray(value) ? value.map(canonical)
  : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;

export function applyFieldGraphEvents(base, buffer, metadata, configuration) {
  const description = metadata?.graph_description, layout = description?.binary?.arrays;
  const n = base?.node_ids?.length;
  if (!n || description?.manifest_sha256 !== base.description?.manifest_sha256
      || configuration?.graph_manifest_sha256 !== description.manifest_sha256
      || !Number.isInteger(description.duration_ms) || description.duration_ms < 1
      || description.duration_ms > 1000 || buffer.byteLength !== description.binary.bytes
      || description.binary.byte_order !== 'little'
      || !Array.isArray(configuration.source_cells) || !configuration.source_cells.length) throw new Error('field_graph_identity');
  const shapes = [['node_ids', '<u8', 8], ['spike_neurons', '<i4', 4], ['spike_times_ms', '<f4', 4]];
  let offset = 0;
  for (const [key, dtype, width] of shapes) {
    const item = layout?.[key];
    if (!item || item.dtype !== dtype || item.offset !== offset || !Number.isSafeInteger(item.count)
        || item.count < 0 || !Array.isArray(item.shape) || item.shape.length !== 1 || item.shape[0] !== item.count) throw new Error('field_graph_layout');
    offset += item.count * width;
  }
  if (offset !== buffer.byteLength || layout.node_ids.count !== n
      || layout.spike_neurons.count !== layout.spike_times_ms.count) throw new Error('field_graph_layout');
  const ids = new BigUint64Array(buffer, layout.node_ids.offset, n);
  if (!ids.every((value, i) => value === base.node_ids[i])) throw new Error('field_graph_nodes');
  const indices = new Int32Array(buffer, layout.spike_neurons.offset, layout.spike_neurons.count);
  const times = new Float32Array(buffer, layout.spike_times_ms.offset, layout.spike_times_ms.count);
  if (configuration.source_cells.some(cell => !Number.isSafeInteger(cell.body_id) || cell.body_id <= 0)) throw new Error('field_graph_sources');
  const counts = new Int32Array(n), sourceIds = configuration.source_cells.map(cell => BigInt(cell.body_id));
  const sourceSet = new Set(sourceIds.map(String)), input = [];
  if (sourceSet.size !== sourceIds.length || sourceIds.some(id => id <= 0n)) throw new Error('field_graph_sources');
  ids.forEach((id, index) => { if (sourceSet.has(String(id))) input.push(index); });
  if (input.length !== sourceIds.length) throw new Error('field_graph_sources');
  const sourceMask = new Uint8Array(n); input.forEach(index => { sourceMask[index] = 1; });
  let outside = 0;
  indices.forEach((index, i) => {
    if (index < 0 || index >= n || !Number.isInteger(times[i]) || times[i] <= 0
        || times[i] > description.duration_ms || (i && times[i] < times[i - 1])) throw new Error('field_graph_events');
    counts[index] += 1; if (!sourceMask[index]) outside += 1;
  });
  const metadataSources = metadata.configuration?.source_cells;
  if (!Array.isArray(metadataSources) || metadataSources.length !== configuration.source_cells.length
      || metadataSources.some((cell, i) => ['body_id', 'child_node_id', 'threshold_mv']
        .some(key => cell[key] !== configuration.source_cells[i][key]))) throw new Error('field_graph_configuration');
  const { electrode_um, reference_um, source_model, coordinate_frame, ...simulation } = configuration.simulation || {};
  if (coordinate_frame !== 'male-cns-v1.0-native-um' || description.duration_ms !== simulation.duration_ms) throw new Error('field_graph_configuration');
  const expected = { source_cells: configuration.source_cells, replay_ids: configuration.replay_ids,
    simulation_parameters: simulation, schedule_parameters: { ...configuration.synapse, duration_ms: simulation.duration_ms },
    recording: { electrode_um, reference_um, source_model }, seed: configuration.seed, acquisition: configuration.acquisition ?? null };
  if (configuration.retain_compartment_crossings === true) expected.retain_compartment_crossings = true;
  if (JSON.stringify(canonical(metadata.configuration)) !== JSON.stringify(canonical(expected))) throw new Error('field_graph_configuration');
  return { ...base, spike_neurons: indices, spike_times_ms: times, counts,
    input_indices: Int32Array.from(input), description: { ...base.description,
      duration_ms: description.duration_ms, spikes: indices.length,
      input_neurons: input.length, active_neurons: counts.reduce((sum, count) => sum + Number(count > 0), 0),
      spikes_outside_input_population: outside, stimulus_region: 'electrical',
      interpretation: 'experimental one-way field-driven event journal' } };
}

export async function verifyFieldGraphEvents(base, graph, graphArtifact, metadataBuffer, metadataArtifact, configuration) {
  async function verify(buffer, artifact) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== artifact?.bytes || !/^[a-f0-9]{64}$/.test(artifact?.sha256 || '')) throw new Error('field_graph_size');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (digest !== artifact.sha256) throw new Error('field_graph_checksum');
  }
  await Promise.all([verify(graph, graphArtifact), verify(metadataBuffer, metadataArtifact)]);
  const metadata = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(metadataBuffer));
  if (metadata.format !== 'field-graph-replay-v1' || metadata.graph_sha256 !== graphArtifact.sha256) throw new Error('field_graph_metadata');
  return applyFieldGraphEvents(base, graph, metadata, configuration);
}
