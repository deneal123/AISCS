import { decodeNeuropil, validateNeuropil } from '../../../src/features/simulator/connectome/neuropil';
import { maleCnsViewPosition } from '../../../src/features/simulator/connectome/connectomeMorphology';

const makeManifest = () => ({ dataset_id: 'male-cns:v1.0-annotated-nonglial', manifest_sha256: 'graph',
  source_frame: 'MaleCNS native unmirrored EM', units: 'um', method: 'vertex-grid-visual-lod-v1', grid_um: 3,
  meshes: [['fullbrain-roi-v4', 90], ['malecns-vnc-neuropil-roi-v0', 24]].flatMap(([dataset, count]) =>
    Array.from({ length: count }, (_, i) => ({ dataset, id: String(i + 1), label: 'region',
      file: `${dataset}-${i + 1}.bin.gz`, sha256: 'a'.repeat(64), source_sha256: 'b'.repeat(64),
      bytes: 50, vertices: 3, triangles: 1, max_vertex_displacement_um: 1 }))) });

test('neuropil manifest binds complete source regions to the current graph', () => {
  const manifest = makeManifest();
  expect(validateNeuropil(manifest, 'graph').meshes).toHaveLength(114);
  expect(() => validateNeuropil(manifest, 'other')).toThrow('neuropil_identity');
  expect(() => validateNeuropil({ ...manifest, meshes: manifest.meshes.slice(1) }, 'graph')).toThrow('neuropil_coverage');
  manifest.meshes[1].file = '../bad';
  expect(() => validateNeuropil(manifest, 'graph')).toThrow('neuropil_manifest');
});

test('decodes native micrometre vertices and rejects invalid triangle indices', () => {
  const item = makeManifest().meshes[0], bytes = new ArrayBuffer(56), view = new DataView(bytes);
  view.setUint32(0, 3, true); view.setUint32(4, 1, true);
  [100, 200, 300, 110, 200, 300, 100, 210, 300].forEach((value, i) => view.setFloat32(8 + i * 4, value, true));
  [0, 1, 2].forEach((value, i) => view.setUint32(44 + i * 4, value, true));
  const decoded = decodeNeuropil(bytes, item);
  expect([...decoded.indices]).toEqual([0, 1, 2]);
  maleCnsViewPosition([100, 200, 300]).forEach((value, i) => expect(decoded.positions[i]).toBeCloseTo(value));
  view.setUint32(52, 3, true);
  expect(() => decodeNeuropil(bytes, item)).toThrow('neuropil_index');
});
