import { createConnectomeLayer } from '../../../src/features/simulator/connectomeLayer';
import { parseConnectome } from '../../../src/features/simulator/connectomeData';

const data = () => ({
  node_ids: new BigUint64Array([1n, 2n, 3n]), positions_mm: new Float32Array([0, 0, 0, 1, 0, 0, 2, 0, 0]),
  edge_pre: new Uint32Array([0, 1]), edge_post: new Uint32Array([1, 2]), edge_sign: new Int8Array([1, -1]),
  spike_times_ms: new Float32Array([1, 3, 5]), spike_neurons: new Int32Array([0, 1, 2]),
  description: { scene: { routes_mm: {} } },
});

test('whole scene retains every neuron; activity and transmissions follow the saved event clock including rewind', () => {
  const layer = createConnectomeLayer(data());
  const cloud = layer.group.children[0], pulses = layer.group.children[2];
  expect(cloud.geometry.attributes.position.count).toBe(3);
  expect(layer.update(0, true, true)).toEqual({ active: 0, delivered: 0 });
  expect(layer.update(3, true, true)).toEqual({ active: 2, delivered: 2 });
  expect([...pulses.geometry.attributes.firedAt.array]).toEqual([1, 3]);
  expect(layer.update(6, true, true)).toEqual({ active: 3, delivered: 3 });
  expect(layer.update(1, true, true)).toEqual({ active: 1, delivered: 1 });
  expect([...pulses.geometry.attributes.firedAt.array]).toEqual([1, -1000]);
  layer.update(1, false, false);
  expect(layer.group.visible).toBe(false);
  expect(cloud.material.depthTest).toBe(true);
  layer.dispose();
});

test('a quiet saved realization never receives artificial spikes from the visible anatomy', () => {
  const quiet = data(); quiet.spike_neurons = new Int32Array(); quiet.spike_times_ms = new Float32Array();
  const layer = createConnectomeLayer(quiet);
  expect(layer.update(50, true, true)).toEqual({ active: 0, delivered: 0 });
  expect([...layer.group.children[0].geometry.attributes.firedAt.array]).toEqual([-1000, -1000, -1000]);
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

test('unresolvable node indices and a false spike count never become a rendered propagation', () => {
  const { buffer, description } = registeredFixture();
  const neurons = new Int32Array(buffer, description.binary.arrays.spike_neurons.offset, 2);
  neurons[1] = 166700;
  expect(() => parseConnectome(buffer, description)).toThrow('content');
  neurons[1] = 1;
  const counts = new Int32Array(buffer, description.binary.arrays.counts.offset, 166700);
  counts[1] = 0;
  expect(() => parseConnectome(buffer, description)).toThrow('event_count');
});
