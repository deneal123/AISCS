const isSha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

async function checked(buffer, artifact) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== artifact?.bytes || !isSha(artifact?.sha256)) throw new Error('state_size');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
  if (digest !== artifact.sha256) throw new Error('state_checksum');
}

export function decodeStateContrast(buffer, description, sourceManifestSha, graphFile, metadataFile, sourceManifest, graph) {
  const { cells, samples, sha256, graph_sha256: graphSha, graph_manifest_sha256: graphManifest,
    field_manifest_sha256: sourceSha } = description || {};
  const sourceFiles = sourceManifest?.files;
  if (!(buffer instanceof ArrayBuffer) || description?.format !== 'lif-state-contrast-v1'
      || !isSha(sha256) || sourceSha !== sourceManifestSha || graphSha !== graphFile?.sha256
      || graphManifest !== graph.description?.manifest_sha256
      || sourceManifest?.format !== 'field-graph-replay-manifest-v1' || !Array.isArray(sourceFiles)
      || sourceFiles.length !== 5 || new Set(sourceFiles.map(file => file.name)).size !== 5
      || !['graph.bin', 'metadata.json', 'signals.npz', 'replay-evidence.jsonl', 'replay-provenance.jsonl']
        .every(name => sourceFiles.some(file => file.name === name))
      || !sourceFiles.some(file => file.name === 'graph.bin' && file.sha256 === graphFile.sha256 && file.bytes === graphFile.bytes)
      || !sourceFiles.some(file => file.name === 'metadata.json' && file.sha256 === metadataFile.sha256 && file.bytes === metadataFile.bytes)
      || !Number.isSafeInteger(cells) || cells < 1 || !Number.isSafeInteger(samples) || samples < 2 || samples > 1001
      || cells * samples > 4000000 || description.step_ms !== 1 || description.byte_order !== 'little'
      || description.ids_dtype !== '<u8' || description.difference_dtype !== '<f4'
      || description.difference_shape?.[0] !== samples || description.difference_shape?.[1] !== cells
      || description.difference_shape?.length !== 2 || description.difference_offset !== cells * 8
      || description.bytes !== buffer.byteLength || buffer.byteLength !== cells * (8 + 4 * samples)
      || samples !== graph.description.duration_ms + 1) throw new Error('state_contract');
  const view = new DataView(buffer), indices = new Int32Array(cells), nodes = graph.node_ids;
  const seen = new Set();
  for (let i = 0; i < cells; i += 1) {
    const id = view.getBigUint64(i * 8, true);
    if (id === 0n || seen.has(id)) throw new Error('state_ids');
    let low = 0, high = nodes.length;
    while (low < high) { const mid = (low + high) >>> 1; if (nodes[mid] < id) low = mid + 1; else high = mid; }
    if (low >= nodes.length || nodes[low] !== id) throw new Error('state_ids');
    indices[i] = low; seen.add(id);
  }
  const values = new Float32Array(cells * samples); let maximum = 0;
  for (let i = 0; i < values.length; i += 1) {
    const value = view.getFloat32(cells * 8 + i * 4, true);
    if (!Number.isFinite(value)) throw new Error('state_values');
    values[i] = value; maximum = Math.max(maximum, Math.abs(value));
  }
  return { indices, values, cells, samples, maximum };
}

export async function verifyStateContrast(binary, binaryFile, descriptionBuffer, descriptionFile,
  sourceBuffer, sourceFile, graphFile, metadataFile, graph) {
  await Promise.all([checked(binary, binaryFile), checked(descriptionBuffer, descriptionFile), checked(sourceBuffer, sourceFile)]);
  const parse = value => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(value));
  const description = parse(descriptionBuffer);
  if (description.sha256 !== binaryFile.sha256) throw new Error('state_checksum');
  return decodeStateContrast(binary, description, sourceFile.sha256, graphFile, metadataFile, parse(sourceBuffer), graph);
}
