import { maleCnsViewPosition } from './connectomeMorphology';

// Geometry remains source SWC, in MaleCNS EM coordinates; body placement is a view-only map.
export async function decodeSelectedMorphology(record, id, expectedManifest) {
  if (record.body_id !== id || record.manifest_sha256 !== expectedManifest
      || record.dataset_id !== 'male-cns:v1.0-annotated-nonglial' || record.source_units !== '8 nm'
      || record.source !== `https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation/skeletons-malecns/skeletons-swc/${id}.swc`
      || !/^[a-f0-9]{64}$/.test(record.sha256 || '') || typeof record.swc !== 'string') throw new Error('morphology_identity');
  const raw = new TextEncoder().encode(record.swc);
  if (raw.byteLength > 8 * 1024 * 1024) throw new Error('morphology_size');
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== record.sha256) throw new Error('morphology_hash');
  const nodes = new Map();
  for (const line of record.swc.split(/\r?\n/)) {
    const row = line.trim();
    if (!row || row.startsWith('#')) continue;
    const fields = row.split(/\s+/);
    if (fields.length !== 7) throw new Error('morphology_row');
    const node = Number(fields[0]), parent = Number(fields[6]), xyz = fields.slice(2, 5).map(Number), radius = Number(fields[5]);
    if (!Number.isSafeInteger(node) || node <= 0 || nodes.has(node) || !Number.isSafeInteger(parent)
        || parent === node || !xyz.every(Number.isFinite) || !Number.isFinite(radius) || radius < 0) throw new Error('morphology_node');
    nodes.set(node, { parent, point: maleCnsViewPosition(xyz.map(value => value * .008)) });
  }
  if (nodes.size !== record.vertices || !nodes.size) throw new Error('morphology_count');
  const segments = [];
  const segmentsByChild = new Map();
  const visited = new Set();
  for (const id of nodes.keys()) {
    const path = new Set();
    let current = id;
    while (current !== -1 && !visited.has(current)) {
      if (!nodes.has(current)) throw new Error('morphology_parent');
      if (path.has(current)) throw new Error('morphology_cycle');
      path.add(current);
      current = nodes.get(current).parent;
    }
    path.forEach(value => visited.add(value));
  }
  for (const [nodeId, { parent, point }] of nodes.entries()) {
    if (parent === -1) continue;
    if (!nodes.has(parent)) throw new Error('morphology_parent');
    segmentsByChild.set(nodeId, { start: nodes.get(parent).point, end: point });
    segments.push(...nodes.get(parent).point, ...point);
  }
  return { positions: new Float32Array(segments), segmentsByChild, cells: 1, vertices: nodes.size, sha256: hash };
}
