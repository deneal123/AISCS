import { Matrix4, Vector3 } from 'three';
import { applyBodyViewCorrection, applyMorphologyLandmarks, maleCnsViewPosition, maleCnsNativePosition, NATIVE_VIEW_MATRIX } from '../../../src/features/simulator/connectome/connectomeMorphology';
import { buildConnectomeRoutes, connectomeCoverage } from '../../../src/features/simulator/connectome/connectomeRoutes';
import { decodeNeuropil } from '../../../src/features/simulator/connectome/neuropil';

function fixture() {
  const data = { node_ids: new BigUint64Array([10n, 20n, 30n]),
    positions_mm: new Float32Array([1, 2, 3, .84, 0, .02, .84, .1, .02]),
    coordinate_kind: new Uint8Array([1, 0, 0]), regions: new Uint8Array(3),
    edge_pre: new Uint32Array([0, 1]), edge_post: new Uint32Array([1, 2]),
    description: { dataset_id: 'male-cns:v1.0-annotated-nonglial',
      scene: { regions: ['brain'], routes_mm: {}, embedding: 'male-cns-flybody-view-only-v2' } } };
  const manifest = { dataset_id: data.description.dataset_id,
    annotations_sha256: 'd27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee',
    source_frame: 'MaleCNS native unmirrored EM', output_units: 'um',
    method: 'nearest-swc-vertex-to-cable-centroid-v1', count: 2, binary: { record_bytes: 24 } };
  const buffer = new ArrayBuffer(48), view = new DataView(buffer);
  [[20n, 600, 200, 170, 12], [30n, 200, 210, 220, 40]].forEach((values, i) => {
    view.setBigUint64(i * 24, values[0], true);
    values.slice(1, 4).forEach((v, j) => view.setFloat32(i * 24 + 8 + j * 4, v, true));
    view.setUint32(i * 24 + 20, values[4], true);
  });
  return { data, buffer, manifest };
}

test('native view removes body-only anisotropic scaling and preserves native micrometre distances', () => {
  const matrix = new Matrix4().set(...NATIVE_VIEW_MATRIX);
  const source = [[393, 200, 180], [493, 200, 180], [393, 300, 180], [393, 200, 280]];
  const restored = source.map(point => {
    const view = maleCnsViewPosition(point);
    maleCnsNativePosition(view).forEach((value, axis) => expect(value).toBeCloseTo(point[axis], 9));
    return new Vector3(...view).applyMatrix4(matrix);
  });
  for (const point of restored.slice(1)) expect(point.distanceTo(restored[0])).toBeCloseTo(.1, 12);
});

test('real neurite coordinates replace the planar fallback while measured somata and source arrays stay intact', () => {
  const { data, buffer, manifest } = fixture(), original = new Float32Array(data.positions_mm);
  const result = applyMorphologyLandmarks(data, buffer, manifest), routes = buildConnectomeRoutes(result);
  expect([...data.positions_mm]).toEqual([...original]);
  expect([...data.coordinate_kind]).toEqual([1, 0, 0]);
  const angle = .3, dx = original[0] * .8 - .75, dz = original[2] + .05;
  expect(result.positions_mm[0]).toBeCloseTo(.75 + Math.cos(angle) * dx + Math.sin(angle) * dz, 6);
  expect(result.positions_mm[1]).toBeCloseTo(original[1], 6);
  expect(result.positions_mm[2]).toBeCloseTo(-.05 - Math.sin(angle) * dx + Math.cos(angle) * dz, 6);
  expect(result.positions_mm[3]).not.toBe(result.positions_mm[6]);
  expect(result.positions_mm[3]).toBeCloseTo(maleCnsViewPosition([600, 200, 170])[0], 5);
  expect(result.positions_mm[4]).toBeCloseTo(.207, 5);
  expect([...result.coordinate_kind]).toEqual([1, 3, 3]);
  expect([...result.morphology_vertices]).toEqual([0, 12, 40]);
  expect(routes.visibleNodes).toEqual([0, 1, 2]);
  expect(routes.visibleEdges).toEqual([0, 1]);
  expect(connectomeCoverage(result)).toEqual({ source: 1, neurite: 2, schematic: 0, hidden: 0 });
});

test('body correction is reversible and never modifies saved positions', () => {
  const { data } = fixture(), original = [...data.positions_mm];
  const corrected = applyBodyViewCorrection(data);
  expect([...data.positions_mm]).toEqual(original);
  expect(corrected.positions_mm[0]).toBeCloseTo(.75 + Math.cos(.3) * (original[0] * .8 - .75)
    + Math.sin(.3) * (original[2] + .05), 6);
  expect(applyBodyViewCorrection(corrected)).toBe(corrected);
});

test('graph, reconstructed landmark and neuropil use the same body-view coordinates', () => {
  const { data, buffer, manifest } = fixture();
  // The saved graph uses the original v2 projection before the body correction.
  data.positions_mm.set([.98, 0, .04], 0);
  const graph = applyMorphologyLandmarks(data, buffer, manifest);
  const item = { vertices: 3, triangles: 1, id: '1', label: 'test', dataset: 'test' };
  const raw = new ArrayBuffer(8 + 12 * (item.vertices + item.triangles));
  const view = new DataView(raw);
  view.setUint32(0, 3, true); view.setUint32(4, 1, true);
  [[393, 200, 180], [600, 200, 170], [393, 201, 180]].forEach((point, i) =>
    point.forEach((v, axis) => view.setFloat32(8 + i * 12 + axis * 4, v, true)));
  [0, 1, 2].forEach((v, i) => view.setUint32(44 + i * 4, v, true));
  const roi = decodeNeuropil(raw, item);
  for (const offset of [0, 3]) {
    for (let axis = 0; axis < 3; axis++) {
      expect(graph.positions_mm[offset + axis]).toBeCloseTo(roi.positions[offset + axis], 6);
    }
  }
});

test('body-only rotation raises the neck and preserves distances in the scaled view', () => {
  const native = [[393, 411.111111, 433.030303], [493, 411.111111, 433.030303]];
  const mapped = native.map(maleCnsViewPosition);
  expect(mapped[0][2]).toBeGreaterThan(-.12);
  expect(new Vector3(...mapped[0]).distanceTo(new Vector3(...mapped[1]))).toBeCloseTo(.1, 10);
  mapped.forEach((point, i) => maleCnsNativePosition(point).forEach((v, axis) => {
    expect(v).toBeCloseTo(native[i][axis], 9);
  }));
});

test.each(['another species', 'MaleCNS mirrored EM', 'JRC2018 template'])('wrong spatial frame %s cannot silently fit this body', source_frame => {
  const { data, buffer, manifest } = fixture();
  expect(() => applyMorphologyLandmarks(data, buffer, { ...manifest, source_frame })).toThrow('identity');
});

test('a landmark cannot overwrite a known soma or attach to a different body identity', () => {
  const { data, buffer, manifest } = fixture(), view = new DataView(buffer);
  view.setBigUint64(0, 10n, true);
  expect(() => applyMorphologyLandmarks(data, buffer, manifest)).toThrow('node');
  view.setBigUint64(0, 15n, true);
  expect(() => applyMorphologyLandmarks(data, buffer, manifest)).toThrow('node');
  expect([...data.coordinate_kind]).toEqual([1, 0, 0]);
});

test('duplicate identities, nonfinite coordinates and truncated data fail before publication', () => {
  const { data, buffer, manifest } = fixture(), view = new DataView(buffer);
  view.setBigUint64(24, 20n, true);
  expect(() => applyMorphologyLandmarks(data, buffer, manifest)).toThrow('order');
  view.setBigUint64(24, 30n, true); view.setFloat32(8, NaN, true);
  expect(() => applyMorphologyLandmarks(data, buffer, manifest)).toThrow('coordinate');
  expect(() => applyMorphologyLandmarks(data, buffer.slice(0, -1), manifest)).toThrow('identity');
});
