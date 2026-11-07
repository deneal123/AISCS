import { createConnectomeLayer } from '../../../src/features/simulator/connectome/connectomeLayer';
import { parseConnectome } from '../../../src/features/simulator/connectome/connectomeData';

const data = () => ({
  node_ids: new BigUint64Array([1n, 2n, 3n]), positions_mm: new Float32Array([0, 0, 0, 1, 0, 0, 2, 0, 0]),
  edge_pre: new Uint32Array([0, 1]), edge_post: new Uint32Array([1, 2]), edge_sign: new Int8Array([1, -1]),
  spike_times_ms: new Float32Array([1, 3, 5]), spike_neurons: new Int32Array([0, 1, 2]),
  input_indices: new Int32Array([0]),
  description: { synaptic_delay_ms: 2, scene: { routes_mm: {} } },
});

test('whole scene retains every neuron; activity and transmissions follow the saved event clock including rewind', () => {
  const layer = createConnectomeLayer(data());
  const cloud = layer.group.children[0], pulses = layer.group.children[1];
  expect(layer.group.children.some(child => child.isLineSegments)).toBe(false);
  expect(cloud.geometry.attributes.position.count).toBe(3);
  expect([...cloud.geometry.attributes.isInput.array]).toEqual([1, 0, 0]);
  expect(layer.update(0, true, true)).toMatchObject({ active: 0, inputActive: 0, delivered: 0 });
  expect(layer.update(3, true, true)).toMatchObject({ active: 2, inputActive: 1, delivered: 2 });
  expect([...pulses.geometry.attributes.firedAt.array]).toEqual([1, 3]);
  expect(layer.update(6, true, true)).toMatchObject({ active: 3, inputActive: 1, delivered: 3 });
  expect(layer.update(1, true, true)).toMatchObject({ active: 1, inputActive: 1, delivered: 1 });
  expect([...pulses.geometry.attributes.firedAt.array]).toEqual([1, -1000]);
  layer.update(1, false, false);
  expect(layer.group.visible).toBe(false);
  expect(cloud.material.depthTest).toBe(true);
  layer.dispose();
});

test('a quiet saved realization never receives artificial spikes from the visible anatomy', () => {
  const quiet = data(); quiet.spike_neurons = new Int32Array(); quiet.spike_times_ms = new Float32Array();
  const layer = createConnectomeLayer(quiet);
  expect(layer.update(50, true, true)).toMatchObject({ active: 0, inputActive: 0, delivered: 0 });
  expect([...layer.group.children[0].geometry.attributes.firedAt.array]).toEqual([-1000, -1000, -1000]);
  layer.dispose();
});

test('source segment crossings follow playback without generating network edge pulses', () => {
  const source = data();
  source.spike_neurons = new Int32Array(); source.spike_times_ms = new Float32Array();
  source.physical_source_indices = Uint32Array.of(0, 0);
  source.physical_source_times_ms = Uint32Array.of(2, 5);
  const layer = createConnectomeLayer(source);
  const cloud = layer.group.children[0], pulses = layer.group.children[1];
  expect(layer.update(3, true, true)).toMatchObject({ active: 0, delivered: 0 });
  expect([...cloud.geometry.attributes.sourceAt.array]).toEqual([2, -1000, -1000]);
  expect([...pulses.geometry.attributes.firedAt.array]).toEqual([-1000, -1000]);
  layer.update(5, true, true);
  expect(cloud.geometry.attributes.sourceAt.array[0]).toBe(5);
  layer.update(1, true, true);
  expect(cloud.geometry.attributes.sourceAt.array[0]).toBe(-1000);
  layer.dispose();
});

test('native view displays source landmarks and real arbors without drawing schematic paths as axons', () => {
  const source = data();
  source.coordinate_kind = new Uint8Array([1, 2, 0]);
  source.description.scene.embedding = 'male-cns-flybody-view-only-v2';
  const original = source.positions_mm.slice(), layer = createConnectomeLayer(source);
  layer.coordinateView(true);
  expect([...layer.group.children[0].geometry.index.array]).toEqual([0, 1]);
  expect(layer.group.children[1].visible).toBe(false);
  expect(layer.group.children[2].visible).toBe(false);
  expect(layer.nativeBounds.isEmpty()).toBe(false);
  expect(source.positions_mm).toEqual(original);
  layer.coordinateView(false);
  expect(layer.group.matrix.elements).toEqual([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  expect(layer.group.children[1].visible).toBe(true);
  layer.dispose();
  const legacy = createConnectomeLayer(data());
  expect(() => legacy.coordinateView(true)).toThrow('native_frame_identity');
  legacy.dispose();
});

test('hiding an unlocated node and incident edges preserves the complete event journal', () => {
  const source = data();
  source.coordinate_kind = new Uint8Array([1, 0, 2]);
  source.regions = new Uint8Array([0, 0, 0]);
  source.description.scene.regions = ['brain'];
  const layer = createConnectomeLayer(source);
  expect([...layer.group.children[0].geometry.index.array]).toEqual([0, 2]);
  expect(layer.group.children[1].geometry.index.count).toBe(0);
  expect(layer.update(6, true, true)).toMatchObject({ active: 3, inputActive: 1, delivered: 3 });
  expect([...layer.group.children[0].geometry.attributes.firedAt.array]).toEqual([1, 3, 5]);
  expect([...source.node_ids]).toEqual([1n, 2n, 3n]);
  layer.dispose();
});

function registeredFixture() {
  const n = 166700;
  const arrays = { node_ids: BigUint64Array.from({ length: n }, (_, i) => BigInt(i + 1)),
    positions_mm: new Float32Array(n * 3), coordinate_kind: new Uint8Array(n), regions: new Uint8Array(n),
    edge_pre: new Uint32Array([0]), edge_post: new Uint32Array([1]), edge_sign: new Int8Array([1]),
    spike_neurons: new Int32Array([0, 1]), spike_times_ms: new Float32Array([1, 3]), counts: new Int32Array(n), input_indices: new Int32Array([0]) };
  arrays.counts[0] = 1; arrays.counts[1] = 1;
  const types = ['<u8', '<f4', '|u1', '|u1', '<u4', '<u4', '|i1', '<i4', '<f4', '<i4', '<i4'];
  let size = 0; const layouts = {};
  Object.entries(arrays).forEach(([name, values], i) => {
    size = Math.ceil(size / 8) * 8;
    layouts[name] = { offset: size, dtype: types[i], count: values.length, shape: [values.length] };
    size += values.byteLength;
  });
  const buffer = new ArrayBuffer(size);
  Object.entries(arrays).forEach(([name, values]) => new Uint8Array(buffer, layouts[name].offset, values.byteLength).set(new Uint8Array(values.buffer)));
  const description = { dataset_id: 'male-cns:v1.0-annotated-nonglial', neurons: n, edges: 25582938,
    engine: 'fly-arena-lif-1ms-2ms-delay-v1', step_ms: 1, synaptic_delay_ms: 2, duration_ms: 200,
    stimulus_region: 'head', spikes: 2, input_neurons: 1, active_neurons: 2, spikes_outside_input_population: 1,
    manifest_sha256: '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2',
    binary: { bytes: size, arrays: layouts }, scene: { display_edges: 1, regions: ['brain'] } };
  return { buffer, description };
}

test('registered scene parsing retains all IDs and rejects source or buffer misrepresentation', () => {
  const { buffer, description } = registeredFixture();
  expect(parseConnectome(buffer, description).node_ids.length).toBe(166700);
  expect(() => parseConnectome(buffer.slice(0, -8), description)).toThrow('identity');
  expect(() => parseConnectome(buffer, { ...description, dataset_id: 'another-brain' })).toThrow('identity');
  description.binary.arrays.spike_neurons.dtype = '<f4';
  expect(() => parseConnectome(buffer, description)).toThrow('layout');
});

test('scene rejects incompatible solver timing and events off the saved time grid', () => {
  const { buffer, description } = registeredFixture();
  for (const patch of [{ synaptic_delay_ms: 3 }, { step_ms: .5 }, { engine: 'another-engine' }, { duration_ms: NaN }]) {
    expect(() => parseConnectome(buffer, { ...description, ...patch })).toThrow('time_contract');
  }
  const times = new Float32Array(buffer, description.binary.arrays.spike_times_ms.offset, 2);
  times[1] = 201; expect(() => parseConnectome(buffer, description)).toThrow('content');
  times[1] = 2.5; expect(() => parseConnectome(buffer, description)).toThrow('content');
  const layer = createConnectomeLayer(data());
  expect(layer.group.children[1].material.uniforms.synapticDelay.value).toBe(2);
  layer.dispose();
});

test('reported population totals and selected body region must agree with the actual binary', () => {
  const { buffer, description } = registeredFixture();
  for (const patch of [{ spikes: 3 }, { active_neurons: 1 }, { input_neurons: 2 }, { spikes_outside_input_population: 0 }]) {
    expect(() => parseConnectome(buffer, { ...description, ...patch })).toThrow('population_counts');
  }
  for (const stimulus_region of ['front_left', 'abdomen', 'unknown']) {
    expect(() => parseConnectome(buffer, { ...description, stimulus_region })).toThrow('input_region');
  }
});

test('notum input must be positioned in the thoracic CNS region', () => {
  const { buffer, description } = registeredFixture();
  description.stimulus_region = 'notum';
  expect(() => parseConnectome(buffer, description)).toThrow('input_region');
  description.scene.regions = ['thorax'];
  expect(parseConnectome(buffer, description).input_indices.length).toBe(1);
});

test('unresolvable node indices and a false spike count never become a rendered propagation', () => {
  const { buffer, description } = registeredFixture();
  const neurons = new Int32Array(buffer, description.binary.arrays.spike_neurons.offset, 2);
  neurons[1] = 166700;
  expect(() => parseConnectome(buffer, description)).toThrow('content');
  neurons[1] = -1;
  expect(() => parseConnectome(buffer, description)).toThrow('content');
  neurons[1] = 1;
  const inputs = new Int32Array(buffer, description.binary.arrays.input_indices.offset, 1);
  inputs[0] = -1;
  expect(() => parseConnectome(buffer, description)).toThrow('content');
  inputs[0] = 0;
  const counts = new Int32Array(buffer, description.binary.arrays.counts.offset, 166700);
  counts[1] = 0;
  expect(() => parseConnectome(buffer, description)).toThrow('event_count');
  counts[0] = 2;
  expect(() => parseConnectome(buffer, description)).toThrow('node_event_count');
});
