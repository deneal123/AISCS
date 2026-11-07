// Recovered neurite landmarks augment only the drawing, never a saved run.
// Positions are in the native, unmirrored MaleCNS EM frame, not template space.
const ROOT = '/assets/simulator/malecns/';
const DATASET = 'male-cns:v1.0-annotated-nonglial';
const ANNOTATIONS = 'd27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee';
const EMBEDDING = 'male-cns-flybody-view-only-v2';
const BODY_VIEW_X_SCALE = .80;
// Display-only fit chosen for the head-to-thorax transition. The angle is not
// an anatomical registration and does not alter native computation coordinates.
const BODY_VIEW_ANGLE = .3;
const BODY_VIEW_SHIFT_Z = 0;
const BODY_VIEW_COS = Math.cos(BODY_VIEW_ANGLE), BODY_VIEW_SIN = Math.sin(BODY_VIEW_ANGLE);
const BODY_VIEW_PIVOT_X = .75, BODY_VIEW_PIVOT_Z = -.05;
const sha256 = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');

const rotateBodyView = ([x, y, z]) => {
  const dx = x - BODY_VIEW_PIVOT_X, dz = z - BODY_VIEW_PIVOT_Z;
  return [BODY_VIEW_PIVOT_X + BODY_VIEW_COS * dx + BODY_VIEW_SIN * dz, y,
    BODY_VIEW_PIVOT_Z - BODY_VIEW_SIN * dx + BODY_VIEW_COS * dz + BODY_VIEW_SHIFT_Z];
};
const unrotateBodyView = ([x, y, z]) => {
  const dx = x - BODY_VIEW_PIVOT_X, dz = z - BODY_VIEW_SHIFT_Z - BODY_VIEW_PIVOT_Z;
  return [BODY_VIEW_PIVOT_X + BODY_VIEW_COS * dx - BODY_VIEW_SIN * dz, y,
    BODY_VIEW_PIVOT_Z + BODY_VIEW_SIN * dx + BODY_VIEW_COS * dz];
};
export const maleCnsViewPosition = xyz => rotateBodyView([
  BODY_VIEW_X_SCALE * (.98 - (xyz[2] - 180) * .00165), (xyz[0] - 393) * .001, .04 - (xyz[1] - 200) * .0009,
]);

// Inverse of v2, in native EM micrometres. Never apply it to v1 or to a
// schematic peripheral glyph. Float32 round-off in the saved view is retained.
export const maleCnsNativePosition = xyz => {
  const view = unrotateBodyView(xyz);
  return [393 + view[1] * 1000, 200 + (.04 - view[2]) / .0009,
    180 + (.98 - view[0] / BODY_VIEW_X_SCALE) / .00165];
};
// Native millimetres centred at [393, 200, 180] um. An additional rigid
// half-turn presents the brain above the VNC without changing native data.
export const NATIVE_VIEW_MATRIX = [
  0, -1, 0, 0,
  -BODY_VIEW_SIN / .9, 0, -BODY_VIEW_COS / .9,
  (.04 - BODY_VIEW_PIVOT_Z + BODY_VIEW_SIN * BODY_VIEW_PIVOT_X
    + BODY_VIEW_COS * (BODY_VIEW_PIVOT_Z + BODY_VIEW_SHIFT_Z)) / .9,
  BODY_VIEW_COS / (1.65 * BODY_VIEW_X_SCALE), 0, -BODY_VIEW_SIN / (1.65 * BODY_VIEW_X_SCALE),
  (BODY_VIEW_PIVOT_X * (1 - BODY_VIEW_COS)
    + BODY_VIEW_SIN * (BODY_VIEW_PIVOT_Z + BODY_VIEW_SHIFT_Z))
    / (1.65 * BODY_VIEW_X_SCALE) - .98 / 1.65,
  0, 0, 0, 1,
];

// The recorded v2 positions stay immutable. This display-only correction uses
// measured source/head bounds; it is not a validated anatomical registration.
export function applyBodyViewCorrection(data) {
  if (data.bodyViewCorrection || data.description.scene.embedding !== EMBEDDING) return data;
  const positions = new Float32Array(data.positions_mm);
  for (let index = 0; index < data.node_ids.length; index += 1) {
    if (data.coordinate_kind[index] > 0) {
      const offset = index * 3;
      positions.set(rotateBodyView([positions[offset] * BODY_VIEW_X_SCALE,
        positions[offset + 1], positions[offset + 2]]), offset);
    }
  }
  return { ...data, positions_mm: positions, bodyViewCorrection: 'male-cns-flybody-ventral-fit-v5' };
}

export function applyMorphologyLandmarks(input, buffer, manifest) {
  const data = applyBodyViewCorrection(input);
  if (manifest.dataset_id !== DATASET || data.description.dataset_id !== DATASET
      || manifest.annotations_sha256 !== ANNOTATIONS || data.description.scene.embedding !== EMBEDDING
      || manifest.source_frame !== 'MaleCNS native unmirrored EM' || manifest.output_units !== 'um'
      || manifest.method !== 'nearest-swc-vertex-to-cable-centroid-v1'
      || manifest.binary?.record_bytes !== 24 || !Number.isSafeInteger(manifest.count) || manifest.count < 1 || manifest.count > 166700
      || buffer.byteLength !== manifest.count * 24) throw new Error('morphology_identity');
  const view = new DataView(buffer), positions = new Float32Array(data.positions_mm), kinds = new Uint8Array(data.coordinate_kind);
  const vertices = new Uint32Array(data.node_ids.length);
  let node = 0, previous = 0n;
  for (let row = 0; row < manifest.count; row += 1) {
    const offset = row * 24, id = view.getBigUint64(offset, true);
    if (id <= previous) throw new Error('morphology_order');
    while (node < data.node_ids.length && data.node_ids[node] < id) node += 1;
    if (data.node_ids[node] !== id || kinds[node] !== 0) throw new Error('morphology_node');
    const xyz = [8, 12, 16].map(at => view.getFloat32(offset + at, true));
    const vertex = view.getUint32(offset + 20, true);
    if (!xyz.every(v => Number.isFinite(v) && v >= 0 && v <= 2000) || !vertex) throw new Error('morphology_coordinate');
    // Same affine map as the registered scene embedding. It is a display map,
    // not anatomical registration or a physical conductor transformation.
    positions.set(maleCnsViewPosition(xyz), node * 3);
    kinds[node] = 3; vertices[node] = vertex; previous = id;
  }
  return { ...data, positions_mm: positions, coordinate_kind: kinds, morphology_vertices: vertices,
    morphology: { count: manifest.count, method: manifest.method, source: manifest.source_page, sha256: manifest.binary.sha256 } };
}

export async function loadMorphologyLandmarks(data, signal) {
  const response = await fetch(ROOT + 'landmarks.json', { signal });
  if (!response.ok) throw new Error('morphology_unavailable');
  const manifest = await response.json();
  if (manifest.binary?.file !== 'landmarks.bin' || manifest.count > 166700) throw new Error('morphology_identity');
  const raw = await fetch(ROOT + 'landmarks.bin', { signal });
  if (!raw.ok) throw new Error('morphology_unavailable');
  const bytes = await raw.arrayBuffer();
  if (await sha256(bytes) !== manifest.binary.sha256) throw new Error('morphology_integrity');
  return applyMorphologyLandmarks(data, bytes, manifest);
}
