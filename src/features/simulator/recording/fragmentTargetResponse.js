const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

export async function verifyFragmentTargetResponse(buffer, artifact, run, graph) {
  const entry = run?.result?.manifest?.files?.find(file => file.name === 'fragment-response.bin');
  const configHash = run?.configuration_sha256;
  const graphHash = run?.configuration?.graph_manifest_sha256;
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== artifact?.bytes
      || artifact.name !== 'fragment-response.bin' || !sha(artifact.sha256)
      || entry?.sha256 !== artifact.sha256 || entry?.bytes !== artifact.bytes
      || !sha(configHash) || !sha(graphHash) || run?.result?.manifest?.configuration_sha256 !== configHash
      || run?.result?.manifest?.graph_sha256 !== graphHash
      || run?.result?.manifest?.kind !== 'experimental-fragment-population'
      || !Array.isArray(run?.configuration?.source_ids)
      || graph?.description?.manifest_sha256 !== graphHash || buffer.byteLength < 76) throw new Error('response_identity');
  const digest = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)));
  if (digest !== artifact.sha256) throw new Error('response_checksum');
  const view = new DataView(buffer), bytes = new Uint8Array(buffer);
  const cells = view.getUint32(4, true), samples = view.getUint32(8, true);
  const format = String.fromCharCode(...bytes.subarray(0, 4));
  const decimated = format === 'FRS3', offset = 76 + (decimated ? samples * 4 : 0);
  const duration = run.configuration.simulation.duration_ms;
  if (!['FRS1', 'FRS2', 'FRS3'].includes(format)
      || hex(bytes.subarray(12, 44)) !== graphHash || hex(bytes.subarray(44, 76)) !== configHash
      || cells < 1 || cells > graph.node_ids.length || cells * samples > 4000000
      || !Number.isInteger(duration) || duration < 1 || duration > 1000
      || (!decimated && samples !== duration + 1)
      || samples < 2 || samples > 1001 || buffer.byteLength !== offset + cells * 8 + cells * samples * 4)
    throw new Error('response_contract');
  const indices = new Int32Array(cells), nodes = graph.node_ids;
  const sources = new Set(run.configuration.source_ids.map(value => String(value)));
  if (format !== 'FRS1' && cells !== nodes.length - sources.size) throw new Error('response_coverage');
  let sampleTimes = null;
  if (decimated) {
    const slots = Math.floor(4000000 / cells), stride = Math.max(1, Math.ceil(duration / (slots - 1)));
    const expected = []; for (let tick = 0; tick < duration; tick += stride) expected.push(tick);
    expected.push(duration);
    if (stride <= 1 || expected.length !== samples) throw new Error('response_times');
    sampleTimes = Uint32Array.from(expected, (tick, index) => {
      if (view.getUint32(76 + 4 * index, true) !== tick) throw new Error('response_times');
      return tick;
    });
  }
  let previous = 0n;
  for (let i = 0; i < cells; i += 1) {
    const id = view.getBigUint64(offset + i * 8, true);
    if (id <= previous || sources.has(String(id))) throw new Error('response_ids');
    let low = 0, high = nodes.length;
    while (low < high) { const mid = (low + high) >>> 1; if (nodes[mid] < id) low = mid + 1; else high = mid; }
    if (low >= nodes.length || nodes[low] !== id) throw new Error('response_ids');
    indices[i] = low; previous = id;
  }
  const values = new Float32Array(cells * samples); let maximum = 0;
  for (let i = 0; i < values.length; i += 1) {
    const value = view.getFloat32(offset + cells * 8 + i * 4, true);
    if (!Number.isFinite(value) || (i < cells && value !== 0)) throw new Error('response_values');
    values[i] = value; maximum = Math.max(maximum, Math.abs(value));
  }
  return { indices, values, cells, samples, sampleTimes, maximum,
    scope: format === 'FRS1' ? 'direct-targets' : 'network' };
}
