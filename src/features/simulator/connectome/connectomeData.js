const constructors = { '<f4': Float32Array, '<u4': Uint32Array, '<i4': Int32Array, '|u1': Uint8Array, '|i1': Int8Array, '<u8': BigUint64Array };
const fields = ['node_ids', 'positions_mm', 'coordinate_kind', 'regions', 'edge_pre', 'edge_post', 'edge_sign', 'spike_neurons', 'spike_times_ms', 'counts', 'input_indices'];
const expectedTypes = ['<u8', '<f4', '|u1', '|u1', '<u4', '<u4', '|i1', '<i4', '<f4', '<i4', '<i4'];

export function parseConnectome(buffer, description) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== description?.binary?.bytes || buffer.byteLength > 64 * 1024 * 1024
      || description.dataset_id !== 'male-cns:v1.0-annotated-nonglial' || description.neurons !== 166700 || description.edges !== 25582938
      || description.manifest_sha256 !== '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2') throw new Error('connectome_identity');
  if (description.engine !== 'fly-arena-lif-1ms-2ms-delay-v1' || description.step_ms !== 1 || description.synaptic_delay_ms !== 2
      || !Number.isFinite(description.duration_ms) || description.duration_ms <= 0) throw new Error('connectome_time_contract');
  const result = {};
  let end = 0;
  fields.forEach((name, index) => {
    const layout = description.binary.arrays?.[name], Constructor = constructors[layout?.dtype];
    if (!Constructor || layout.dtype !== expectedTypes[index] || !Number.isSafeInteger(layout.offset) || layout.offset < end || layout.offset % 8
        || !Number.isSafeInteger(layout.count) || layout.count < 0 || layout.offset + layout.count * Constructor.BYTES_PER_ELEMENT > buffer.byteLength
        || !Array.isArray(layout.shape) || layout.shape.some(value => !Number.isSafeInteger(value) || value < 0)
        || layout.shape.reduce((n, value) => n * value, 1) !== layout.count) throw new Error('connectome_layout');
    result[name] = new Constructor(buffer, layout.offset, layout.count);
    end = layout.offset + layout.count * Constructor.BYTES_PER_ELEMENT;
  });
  const n = description.neurons, edges = description.scene?.display_edges;
  if (result.node_ids.length !== n || result.positions_mm.length !== n * 3 || result.counts.length !== n
      || result.coordinate_kind.length !== n || result.regions.length !== n || result.edge_pre.length !== edges
      || result.edge_post.length !== edges || result.edge_sign.length !== edges || edges > 24000
      || result.spike_times_ms.length !== result.spike_neurons.length
      || !result.positions_mm.every(Number.isFinite) || !result.counts.every(value => value >= 0)
      || !result.coordinate_kind.every(value => value <= 2) || !result.regions.every(value => value < description.scene.regions.length)
      || !result.edge_pre.every(value => value < n) || !result.edge_post.every(value => value < n)
      || !result.edge_sign.every(value => [-1, 0, 1].includes(value))
      || !result.input_indices.every(value => value >= 0 && value < n) || !result.spike_neurons.every(value => value >= 0 && value < n)
      || !result.spike_times_ms.every((value, i, values) => Number.isFinite(value) && value > 0 && value <= description.duration_ms
        && Math.abs(value / description.step_ms - Math.round(value / description.step_ms)) < 1e-5 && (!i || value >= values[i - 1]))
      || !result.node_ids.every((value, i, values) => value > 0n && (!i || value > values[i - 1]))) throw new Error('connectome_content');
  if (result.counts.reduce((sum, value) => sum + value, 0) !== result.spike_neurons.length) throw new Error('connectome_event_count');
  const observed = new Uint32Array(n);
  result.spike_neurons.forEach(index => { observed[index] += 1; });
  if (!result.counts.every((count, index) => count === observed[index])) throw new Error('connectome_node_event_count');
  if (!result.input_indices.every((index, i, values) => !i || index > values[i - 1])) throw new Error('connectome_input_order');
  const inputs = new Uint8Array(n);
  result.input_indices.forEach(index => { inputs[index] = 1; });
  const active = observed.reduce((sum, count) => sum + Number(count > 0), 0);
  const outside = result.spike_neurons.reduce((sum, index) => sum + Number(!inputs[index]), 0);
  if (description.spikes !== result.spike_neurons.length || description.input_neurons !== result.input_indices.length
      || description.active_neurons !== active || description.spikes_outside_input_population !== outside) throw new Error('connectome_population_counts');
  const legRegions = ['front_left', 'front_right', 'middle_left', 'middle_right', 'hind_left', 'hind_right'];
  const regions = description.stimulus_region === 'head' ? ['brain']
    : description.stimulus_region === 'notum' ? ['thorax']
    : description.stimulus_region === 'thorax' ? legRegions : legRegions.includes(description.stimulus_region) ? [description.stimulus_region] : [];
  if (!regions.length || !result.input_indices.every(index => regions.includes(description.scene.regions[result.regions[index]]))) throw new Error('connectome_input_region');
  return { ...result, description };
}

export async function verifyConnectome(buffer, artifact, description) {
  if (buffer.byteLength !== artifact.bytes) throw new Error('connectome_size');
  const checksum = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (checksum !== artifact.sha256) throw new Error('connectome_integrity');
  return parseConnectome(buffer, description);
}
