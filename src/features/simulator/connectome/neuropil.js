import { maleCnsViewPosition } from './connectomeMorphology';
import { simulationApi } from '../api';

const groups = { 'fullbrain-roi-v4': 90, 'malecns-vnc-neuropil-roi-v0': 24 };
const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
  .map(value => value.toString(16).padStart(2, '0')).join('');

export function validateNeuropil(manifest, graphHash) {
  if (manifest?.dataset_id !== 'male-cns:v1.0-annotated-nonglial' || manifest.manifest_sha256 !== graphHash
      || manifest.source_frame !== 'MaleCNS native unmirrored EM' || manifest.units !== 'um'
      || manifest.method !== 'vertex-grid-visual-lod-v1' || !Number.isFinite(manifest.grid_um)
      || manifest.grid_um <= 0 || manifest.grid_um > 10 || !Array.isArray(manifest.meshes)) throw new Error('neuropil_identity');
  const counts = Object.fromEntries(Object.keys(groups).map(key => [key, 0])), seen = new Set();
  for (const item of manifest.meshes) {
    if (!item || !Object.hasOwn(groups, item.dataset) || !/^[1-9]\d*$/.test(item.id)
        || seen.has(`${item.dataset}:${item.id}`) || item.file !== `${item.dataset}-${item.id}.bin.gz`
        || typeof item.label !== 'string' || !item.label || item.label.length > 100
        || !/^[a-f0-9]{64}$/.test(item.sha256) || !/^[a-f0-9]{64}$/.test(item.source_sha256)
        || !Number.isSafeInteger(item.bytes) || item.bytes < 1 || item.bytes > 16000000
        || !Number.isSafeInteger(item.vertices) || item.vertices < 3 || item.vertices > 1000000
        || !Number.isSafeInteger(item.triangles) || item.triangles < 1 || item.triangles > 2000000
        || !Number.isFinite(item.max_vertex_displacement_um) || item.max_vertex_displacement_um < 0
        || item.max_vertex_displacement_um > Math.sqrt(3) * manifest.grid_um + 1e-9) throw new Error('neuropil_manifest');
    seen.add(`${item.dataset}:${item.id}`); counts[item.dataset] += 1;
  }
  if (Object.keys(groups).some(key => counts[key] !== groups[key])) throw new Error('neuropil_coverage');
  return manifest;
}

export function decodeNeuropil(buffer, item) {
  const expected = 8 + 12 * (item.vertices + item.triangles);
  if (buffer.byteLength !== expected) throw new Error('neuropil_size');
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== item.vertices || view.getUint32(4, true) !== item.triangles) throw new Error('neuropil_layout');
  const positions = new Float32Array(item.vertices * 3), indices = new Uint32Array(item.triangles * 3);
  for (let vertex = 0; vertex < item.vertices; vertex += 1) {
    const xyz = [0, 1, 2].map(axis => view.getFloat32(8 + vertex * 12 + axis * 4, true));
    if (!xyz.every(value => Number.isFinite(value) && value >= 0 && value <= 2000)) throw new Error('neuropil_coordinate');
    positions.set(maleCnsViewPosition(xyz), vertex * 3);
  }
  const offset = 8 + item.vertices * 12;
  for (let i = 0; i < indices.length; i += 1) {
    indices[i] = view.getUint32(offset + 4 * i, true);
    if (indices[i] >= item.vertices) throw new Error('neuropil_index');
  }
  return { id: item.id, label: item.label, dataset: item.dataset, positions, indices };
}

async function unzip(bytes, maximum, signal) {
  const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();
  const buffer = new Uint8Array(maximum); let size = 0;
  try {
    for (;;) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const { done, value } = await reader.read();
      if (done) break;
      if (size + value.length > maximum) throw new Error('neuropil_size');
      buffer.set(value, size); size += value.length;
    }
    return buffer.buffer.slice(0, size);
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export async function loadNeuropil(runId, graphHash, signal, onBatch) {
  const manifest = validateNeuropil(await simulationApi.neuropil(runId, signal), graphHash);
  for (let start = 0; start < manifest.meshes.length; start += 4) {
    const meshes = await Promise.all(manifest.meshes.slice(start, start + 4).map(async item => {
      const bytes = await simulationApi.neuropilChunk(runId, item.file, signal);
      if (bytes.byteLength !== item.bytes || await digest(bytes) !== item.sha256) throw new Error('neuropil_hash');
      const raw = await unzip(bytes, 8 + 12 * (item.vertices + item.triangles), signal);
      return decodeNeuropil(raw, item);
    }));
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    onBatch(meshes);
  }
}
