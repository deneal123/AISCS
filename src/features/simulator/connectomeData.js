const constructors = { '<f4': Float32Array, '<u4': Uint32Array, '<i4': Int32Array, '|u1': Uint8Array, '|i1': Int8Array, '<u8': BigUint64Array };
const fields = ['node_ids', 'positions_mm', 'coordinate_kind', 'regions', 'edge_pre', 'edge_post', 'edge_sign', 'spike_neurons', 'spike_times_ms', 'counts', 'input_indices'];
const expectedTypes = ['<u8', '<f4', '|u1', '|u1', '<u4', '<u4', '|i1', '<i4', '<f4', '<i4', '<i4'];

export function parseConnectome(buffer, description) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== description?.binary?.bytes || buffer.byteLength > 64 * 1024 * 1024
      || description.dataset_id !== 'male-cns:v1.0-annotated-nonglial' || description.neurons !== 166700 || description.edges !== 25582938
      || description.manifest_sha256 !== '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2') throw new Error('connectome_identity');
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
      || !result.input_indices.every(value => value < n) || !result.spike_neurons.every(value => value < n)
      || !result.spike_times_ms.every((value, i, values) => Number.isFinite(value) && value > 0 && (!i || value >= values[i - 1]))
      || !result.node_ids.every((value, i, values) => value > 0n && (!i || value > values[i - 1]))) throw new Error('connectome_content');
  if (result.counts.reduce((sum, value) => sum + value, 0) !== result.spike_neurons.length) throw new Error('connectome_event_count');
  return { ...result, description };
}

export async function verifyConnectome(buffer, artifact, description) {
  if (buffer.byteLength !== artifact.bytes) throw new Error('connectome_size');
  const checksum = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (checksum !== artifact.sha256) throw new Error('connectome_integrity');
  return parseConnectome(buffer, description);
}
