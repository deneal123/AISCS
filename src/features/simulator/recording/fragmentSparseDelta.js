const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

async function verifySparseDelta(buffer, artifact, run, graph, { name, kind, sources, duration }) {
  const entry = run?.result?.manifest?.files?.find(file => file.name === name);
  const graphHash = run?.configuration?.graph_manifest_sha256, configHash = run?.configuration_sha256;
  if (!(buffer instanceof ArrayBuffer) || artifact?.name !== name
      || buffer.byteLength !== artifact.bytes || !sha(artifact.sha256)
      || entry?.bytes !== artifact.bytes || entry?.sha256 !== artifact.sha256
      || !sha(graphHash) || !sha(configHash) || run?.result?.manifest?.graph_sha256 !== graphHash
      || run?.result?.manifest?.configuration_sha256 !== configHash
      || run?.result?.manifest?.kind !== kind
      || graph?.description?.manifest_sha256 !== graphHash
      || !Array.isArray(sources) || !sources.length || buffer.byteLength < 80) throw new Error('sparse_identity');
  if (hex(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))) !== artifact.sha256) throw new Error('sparse_checksum');
  const view = new DataView(buffer), bytes = new Uint8Array(buffer);
  const nodes = view.getUint32(4, true), samples = view.getUint32(8, true), count = view.getUint32(12, true);
  const indexOffset = 80 + 4 * (samples + 1), valueOffset = indexOffset + 4 * count;
  if (String.fromCharCode(...bytes.subarray(0, 4)) !== 'SPD1'
      || nodes !== graph.node_ids.length || samples !== duration + 1
      || samples < 2 || samples > 1001 || count > 4000000 || buffer.byteLength !== valueOffset + 4 * count
      || hex(bytes.subarray(16, 48)) !== graphHash || hex(bytes.subarray(48, 80)) !== configHash) throw new Error('sparse_contract');
  const offsets = new Uint32Array(samples + 1), sparseIndices = new Uint32Array(count), values = new Float32Array(count);
  for (let i = 0; i <= samples; i += 1) {
    offsets[i] = view.getUint32(80 + 4 * i, true);
    if (offsets[i] > count || (i && offsets[i] < offsets[i - 1])) throw new Error('sparse_offsets');
  }
  if (offsets[0] !== 0 || offsets[1] !== 0 || offsets[samples] !== count) throw new Error('sparse_offsets');
  const sourceSet = new Set(sources.map(value => String(value)));
  if (sourceSet.size !== sources.length || sourceSet.size > nodes) throw new Error('sparse_sources');
  const indices = Int32Array.from({ length: nodes - sourceSet.size }, () => 0);
  let cursor = 0;
  for (let i = 0; i < nodes; i += 1) if (!sourceSet.has(String(graph.node_ids[i]))) indices[cursor++] = i;
  if (cursor !== indices.length) throw new Error('sparse_sources');
  let maximum = 0;
  for (let tick = 0; tick < samples; tick += 1) {
    let previous = -1;
    for (let i = offsets[tick]; i < offsets[tick + 1]; i += 1) {
      const index = view.getUint32(indexOffset + 4 * i, true), value = view.getFloat32(valueOffset + 4 * i, true);
      if (index <= previous || index >= nodes || sourceSet.has(String(graph.node_ids[index]))
          || !Number.isFinite(value) || value === 0) throw new Error('sparse_values');
      sparseIndices[i] = index; values[i] = value; maximum = Math.max(maximum, Math.abs(value)); previous = index;
    }
  }
  return { indices, sparseIndices, offsets, values, cells: indices.length, samples, maximum, scope: 'network', sparse: true };
}

export function verifyFragmentSparseDelta(buffer, artifact, run, graph) {
  return verifySparseDelta(buffer, artifact, run, graph, { name: 'fragment-delta.bin',
    kind: 'experimental-fragment-population', sources: run?.configuration?.source_ids,
    duration: run?.configuration?.simulation?.duration_ms });
}

export async function verifyCoupledSparseDelta(buffer, artifact, run, graph) {
  const preview = run?.result?.preview;
  if (!['converged', 'converged_partial'].includes(preview?.status)
      || preview.graph_sha256 !== run?.configuration?.graph_manifest_sha256
      || preview.source_cells !== preview.source_ids?.length
      || !Number.isInteger(preview.duration_ms) || preview.duration_ms < 1
      || !preview.source_ids?.every(id => Number.isSafeInteger(id) && id > 0)) {
    throw new Error('coupled_identity');
  }
  return verifySparseDelta(buffer, artifact, run, graph, { name: 'coupled-delta.bin',
    kind: 'experimental-coupled-population', sources: preview.source_ids, duration: preview.duration_ms });
}
