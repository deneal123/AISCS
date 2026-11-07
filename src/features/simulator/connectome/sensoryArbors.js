import { maleCnsViewPosition } from './connectomeMorphology';

const ROOT = '/assets/simulator/malecns/';
const REGIONS = ['head', 'notum', 'front_left', 'front_right', 'middle_left', 'middle_right', 'hind_left', 'hind_right'];
const sha256 = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');

export function validateArborManifest(manifest, data) {
  if (manifest.dataset_id !== data.description.dataset_id || manifest.annotations_sha256 !== data.description.annotations_sha256
    || manifest.source_frame !== 'MaleCNS native unmirrored EM' || manifest.units !== 'um' || manifest.record_bytes !== 16
    || manifest.encoding !== 'gzip' || manifest.method !== 'all-source-swc-vertices-and-parent-segments-v1'
    || manifest.display_embedding !== data.description.scene.embedding || manifest.display_embedding !== 'male-cns-flybody-view-only-v2'
    || manifest.neurons !== 3824 || Object.keys(manifest.bundles || {}).length !== REGIONS.length) throw new Error('arbor_identity');
  const all = new Set();
  for (const region of REGIONS) {
    const bundle = manifest.bundles[region];
    if (bundle?.file !== `arbors-${region}.bin.gz` || !Number.isSafeInteger(bundle.bytes) || bundle.bytes < 16 || bundle.bytes > 16e6
      || !Number.isSafeInteger(bundle.compressed_bytes) || bundle.compressed_bytes < 1 || bundle.compressed_bytes > bundle.bytes
      || !/^[a-f0-9]{64}$/.test(bundle.sha256) || !Array.isArray(bundle.cells) || bundle.cells.length < 1) throw new Error('arbor_bundle');
    let end = 0, previous = 0n;
    for (const cell of bundle.cells) {
      if (!/^[1-9]\d{0,19}$/.test(cell.id) || BigInt(cell.id) <= previous || all.has(cell.id)
        || cell.start !== end || !Number.isSafeInteger(cell.count) || cell.count < 1 || cell.count > 500000
        || !/^[a-f0-9]{64}$/.test(cell.source_sha256)) throw new Error('arbor_cell');
      end += cell.count; previous = BigInt(cell.id); all.add(cell.id);
    }
    if (end * 16 !== bundle.bytes) throw new Error('arbor_layout');
  }
  if (all.size !== manifest.neurons) throw new Error('arbor_coverage');
  const wanted = new Map(Array.from(data.input_indices, index => [data.node_ids[index].toString(), index]));
  if (!wanted.size || [...wanted.keys()].some(id => !all.has(id))) throw new Error('arbor_input_coverage');
  return wanted;
}

export function decodeArborBundle(buffer, bundle, wanted) {
  if (buffer.byteLength !== bundle.bytes || buffer.byteLength % 16) throw new Error('arbor_size');
  const view = new DataView(buffer), selected = [], cellRows = [];
  let segments = 0;
  for (const cell of bundle.cells) {
    if (!wanted.has(cell.id)) continue;
    const parents = new Int32Array(cell.count), positions = new Float32Array(cell.count * 3);
    let roots = 0;
    for (let row = 0; row < cell.count; row += 1) {
      const offset = (cell.start + row) * 16;
      const xyz = [0, 4, 8].map(axis => view.getFloat32(offset + axis, true));
      const parent = view.getInt32(offset + 12, true);
      if (!xyz.every(v => Number.isFinite(v) && v >= 0 && v <= 2000) || parent < -1 || parent >= cell.count || parent === row) throw new Error('arbor_vertex');
      parents[row] = parent; positions.set(maleCnsViewPosition(xyz), row * 3);
      if (parent === -1) roots += 1;
    }
    // A valid forest may contain several disconnected reconstructed fragments.
    const visited = new Uint8Array(cell.count);
    for (let row = 0; row < cell.count; row += 1) {
      let at = row;
      while (at !== -1 && visited[at] === 0) { visited[at] = 1; at = parents[at]; }
      if (at !== -1 && visited[at] === 1) throw new Error('arbor_cycle');
      at = row;
      while (at !== -1 && visited[at] === 1) { visited[at] = 2; at = parents[at]; }
    }
    if (!roots) throw new Error('arbor_root');
    segments += cell.count - roots;
    selected.push({ index: wanted.get(cell.id), parents, positions }); cellRows.push(cell);
  }
  const positions = new Float32Array(segments * 6), nodeIndices = new Float32Array(segments * 2);
  let edge = 0;
  for (const cell of selected) for (let row = 0; row < cell.parents.length; row += 1) {
    const parent = cell.parents[row];
    if (parent < 0) continue;
    positions.set(cell.positions.subarray(parent * 3, parent * 3 + 3), edge * 6);
    positions.set(cell.positions.subarray(row * 3, row * 3 + 3), edge * 6 + 3);
    nodeIndices.set([cell.index, cell.index], edge * 2); edge += 1;
  }
  return { positions, nodeIndices, cells: cellRows.length, vertices: cellRows.reduce((sum, cell) => sum + cell.count, 0) };
}

async function decompress(bytes, expected, signal) {
  if (typeof DecompressionStream === 'undefined') throw new Error('arbor_gzip');
  const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();
  const result = new Uint8Array(expected); let offset = 0;
  try {
    for (;;) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const { done, value } = await reader.read();
      if (done) break;
      if (offset + value.length > expected) throw new Error('arbor_size');
      result.set(value, offset); offset += value.length;
    }
    if (offset !== expected) throw new Error('arbor_size');
    return result.buffer;
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export async function loadSensoryArbors(data, signal) {
  const response = await fetch(ROOT + 'arbors.json', { signal });
  if (!response.ok) throw new Error('arbor_unavailable');
  const manifest = await response.json(), wanted = validateArborManifest(manifest, data);
  const selected = REGIONS.filter(region => manifest.bundles[region].cells.some(cell => wanted.has(cell.id)));
  const parts = [];
  for (const region of selected) {
    const bundle = manifest.bundles[region], file = await fetch(ROOT + bundle.file, { signal });
    if (!file.ok) throw new Error('arbor_unavailable');
    const bytes = await file.arrayBuffer();
    if (bytes.byteLength !== bundle.compressed_bytes || await sha256(bytes) !== bundle.sha256) throw new Error('arbor_integrity');
    parts.push(decodeArborBundle(await decompress(bytes, bundle.bytes, signal), bundle, wanted));
  }
  if (parts.reduce((sum, part) => sum + part.cells, 0) !== wanted.size) throw new Error('arbor_input_coverage');
  const positions = new Float32Array(parts.reduce((sum, part) => sum + part.positions.length, 0));
  const nodeIndices = new Float32Array(positions.length / 3); let offset = 0;
  for (const part of parts) { positions.set(part.positions, offset); nodeIndices.set(part.nodeIndices, offset / 3); offset += part.positions.length; }
  return { positions, nodeIndices, cells: wanted.size, vertices: parts.reduce((sum, part) => sum + part.vertices, 0) };
}
