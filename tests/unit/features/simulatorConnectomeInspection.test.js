import * as THREE from 'three';
import { connectionPulseProgress, inspectConnectomeNode, selectedNodePosition, selectedNodeVisible } from '../../../src/features/simulator/connectome/connectomeInspection';
import { createConnectomeLayer } from '../../../src/features/simulator/connectome/connectomeLayer';
import { NATIVE_VIEW_MATRIX } from '../../../src/features/simulator/connectome/connectomeMorphology';

const fixture = () => ({
  node_ids: new BigUint64Array([9007199254740993n, 9007199254740994n]),
  positions_mm: new Float32Array([0, 0, 0, 1, 0, 0]), coordinate_kind: new Uint8Array([3, 1]),
  regions: new Uint8Array([0, 1]), input_indices: new Int32Array([0]),
  spike_neurons: new Int32Array([0, 1, 0]), spike_times_ms: new Float32Array([30, 32, 40]), counts: new Int32Array([2, 1]),
  edge_pre: new Uint32Array([0]), edge_post: new Uint32Array([1]), edge_sign: new Int8Array([1]),
  description: { synaptic_delay_ms: 2, scene: { regions: ['front_left', 'brain'], routes_mm: {} } },
});

test('visible pulses follow recorded presynaptic spikes and the model delay in the correct direction', () => {
  expect(connectionPulseProgress('outgoing', 31, 30, 2)).toBe(.5);
  expect(connectionPulseProgress('outgoing', 30, 30, 2)).toBe(0);
  expect(connectionPulseProgress('incoming', 30, 30, 2)).toBe(1);
  expect(connectionPulseProgress('incoming', 31.5, 30, 2)).toBe(.25);
  for (const time of [29, 32, 33]) expect(connectionPulseProgress('outgoing', time, 30, 2)).toBeNull();
  expect(connectionPulseProgress('incoming', 30, null, 2)).toBeNull();
  expect(connectionPulseProgress('bad', 30, 30, 2)).toBeNull();
});

test('selection states whether a position is a neurite, schematic, or unavailable', () => {
  const source = fixture();
  expect(selectedNodePosition(source, '9007199254740993', false)).toContain('отростка');
  expect(selectedNodeVisible(source, '9007199254740993', false)).toBe(true);
  expect(selectedNodePosition(source, '9007199254740994', false)).toContain('совмещение с телом');
  source.coordinate_kind[0] = 0;
  expect(selectedNodePosition(source, '9007199254740993', true)).toContain('точка не показана');
  expect(selectedNodeVisible(source, '9007199254740993', true)).toBe(false);
  expect(selectedNodePosition(source, '9007199254740993', false)).toContain('нет отображаемого положения');
  source.description.scene.routes_mm.front_left = [[0, 0, 0], [1, 0, 0]];
  expect(selectedNodePosition(source, '9007199254740993', false)).toContain('условно');
  expect(selectedNodeVisible(source, '9007199254740993', false)).toBe(true);
  expect(selectedNodePosition(source, '999', false)).toContain('отсутствует');
  expect(selectedNodePosition(source, 'not-an-id', false)).toBeNull();
});

test('inspection preserves an exact 64-bit ID and distinguishes a neurite landmark from a soma', () => {
  const source = fixture();
  const before = inspectConnectomeNode(source, 0, 29);
  expect(before).toMatchObject({ id: '9007199254740993', coordinateKind: 3, isInput: true,
    deliveredSpikes: 0, firstSpikeMs: 30, lastSpikeMs: null, totalSpikes: 2 });
  expect(before.coordinateName).toContain('не сома');
  expect(before.displayedOutgoing).toEqual([{ targetId: '9007199254740994', sign: 1 }]);
  expect(inspectConnectomeNode(source, 1, 35).displayedOutgoing).toEqual([]);
  expect(inspectConnectomeNode(source, 0, 35)).toMatchObject({ deliveredSpikes: 1, lastSpikeMs: 30 });
  expect(inspectConnectomeNode(source, 0, 41)).toMatchObject({ deliveredSpikes: 2, lastSpikeMs: 40 });
  expect(inspectConnectomeNode(source, 1, 29)).toMatchObject({ isInput: false, coordinateKind: 1 });
  source.description.scene.embedding = 'male-cns-flybody-view-only-v2';
  source.morphology_vertices = new Uint32Array([19, 0]);
  expect(inspectConnectomeNode(source, 0, 35)).toMatchObject({ nativeUm: [393, expect.any(Number), expect.any(Number)], morphologyVertex: 19 });
  source.coordinate_kind[0] = 0;
  expect(inspectConnectomeNode(source, 0, 35).nativeUm).toBeNull();
  for (const index of [-1, 0.5, 2, NaN]) expect(inspectConnectomeNode(source, index, 35)).toBeNull();
});

test('ray inspection selects a real plotted landmark and reads events at the model clock', () => {
  const layer = createConnectomeLayer(fixture());
  expect(layer.selectNode('9007199254740994')).toBe(1);
  expect(layer.nodeWorldPosition('9007199254740994').toArray()).toEqual([1, 0, 0]);
  expect(layer.nodeWorldPosition('123')).toBeNull();
  expect(layer.group.children[0].material.uniforms.selectedNode.value).toBe(1);
  expect(layer.selectNode('123')).toBe(-1);
  expect(layer.group.children[0].material.uniforms.selectedNode.value).toBe(-1);
  layer.group.updateMatrixWorld(true);
  const ray = new THREE.Raycaster(new THREE.Vector3(0, 0, 5), new THREE.Vector3(0, 0, -1));
  ray.params.Points.threshold = .01;
  expect(layer.inspect(ray, 35)).toMatchObject({ id: '9007199254740993', deliveredSpikes: 1 });
  ray.ray.origin.x = .5;
  expect(layer.inspect(ray, 35)).toBeNull();
  layer.update(35, true, false);
  ray.ray.origin.x = 0;
  expect(layer.inspect(ray, 35)).toBeNull();
  layer.dispose();
});

test('focus coordinates follow the native frame and exclude missing morphology', () => {
  const data = fixture();
  data.description.scene.embedding = 'male-cns-flybody-view-only-v2';
  data.coordinate_kind[0] = 0;
  const layer = createConnectomeLayer(data);
  layer.coordinateView(true);
  const expected = new THREE.Vector3(1, 0, 0).applyMatrix4(new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX));
  expect(layer.nodeWorldPosition('9007199254740994').distanceTo(expected)).toBeLessThan(1e-8);
  expect(layer.nodeWorldPosition('9007199254740993')).toBeNull();
  layer.dispose();
});
