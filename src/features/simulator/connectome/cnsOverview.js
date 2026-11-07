import { maleCnsViewPosition } from './connectomeMorphology';
import { simulationApi } from '../api';

export function validateOverview(manifest, graphHash) {
  if (manifest?.dataset_id !== 'male-cns:v1.0-annotated-nonglial'
      || manifest.manifest_sha256 !== graphHash || manifest.source_frame !== 'MaleCNS native unmirrored EM'
      || manifest.units !== 'um' || manifest.method !== 'evenly-sampled-original-swc-edges-v1'
      || manifest.record_bytes !== 28 || !Number.isSafeInteger(manifest.edges_per_neuron_max)
      || manifest.edges_per_neuron_max < 1 || manifest.edges_per_neuron_max > 32
      || !Array.isArray(manifest.chunks)) throw new Error('overview_identity');
  let start = 0;
  for (const chunk of manifest.chunks) {
    if (chunk.start !== start || chunk.file !== `overview-${String(start).padStart(6, '0')}.bin.gz`
        || !Number.isSafeInteger(chunk.cells) || chunk.cells < 1 || chunk.cells > 10000
        || !Number.isSafeInteger(chunk.cells_with_edges) || chunk.cells_with_edges < 0 || chunk.cells_with_edges > chunk.cells
        || !Number.isSafeInteger(chunk.bytes) || chunk.bytes < 1 || chunk.bytes > 16000000
        || !/^[a-f0-9]{64}$/.test(chunk.sha256 || '')) throw new Error('overview_chunk');
    start += chunk.cells;
  }
  if (start !== 166700) throw new Error('overview_coverage');
  return manifest;
}

async function unzip(bytes, maximum, signal) {
  const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();
  const buffer = new Uint8Array(maximum); let size = 0;
  try {
    for (;;) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const { done, value } = await reader.read();
      if (done) break;
      if (size + value.length > maximum) throw new Error('overview_size');
      buffer.set(value, size); size += value.length;
    }
    return buffer.buffer.slice(0, size);
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export function decodeOverviewChunk(buffer, chunk, limit) {
  if (buffer.byteLength % 28 || buffer.byteLength > chunk.cells * limit * 28) throw new Error('overview_size');
  const n = buffer.byteLength / 28, view = new DataView(buffer);
  const positions = new Float32Array(n * 6), nodeIndices = new Float32Array(n * 2);
  let previous = -1, count = 0, cells = 0;
  for (let i = 0; i < n; i += 1) {
    const offset = i * 28, node = view.getUint32(offset, true);
    if (node < chunk.start || node >= chunk.start + chunk.cells || node < previous) throw new Error('overview_index');
    if (node !== previous) { count = 0; cells += 1; } count += 1;
    if (count > limit) throw new Error('overview_index');
    for (let endpoint = 0; endpoint < 2; endpoint += 1) {
      const xyz = [0, 1, 2].map(axis => view.getFloat32(offset + 4 + endpoint * 12 + axis * 4, true));
      if (!xyz.every(value => Number.isFinite(value) && value >= 0 && value <= 2000)) throw new Error('overview_coordinate');
      positions.set(maleCnsViewPosition(xyz), i * 6 + endpoint * 3);
      nodeIndices[i * 2 + endpoint] = node;
    }
    previous = node;
  }
  if (cells !== chunk.cells_with_edges) throw new Error('overview_coverage');
  return { positions, nodeIndices, cells, segments: n };
}

export async function loadOverview(runId, graphHash, signal, onChunk) {
  const manifest = validateOverview(await simulationApi.overview(runId, signal), graphHash);
  for (const chunk of manifest.chunks) {
    const bytes = await simulationApi.overviewChunk(runId, chunk.file, signal);
    if (bytes.byteLength !== chunk.bytes) throw new Error('overview_size');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
    if (digest !== chunk.sha256) throw new Error('overview_hash');
    const raw = await unzip(bytes, chunk.cells * manifest.edges_per_neuron_max * 28, signal);
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    onChunk(decodeOverviewChunk(raw, chunk, manifest.edges_per_neuron_max));
  }
}
