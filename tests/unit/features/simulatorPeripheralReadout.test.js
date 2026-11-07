import fs from 'fs';
import path from 'path';
import { webcrypto } from 'crypto';
import { TextDecoder } from 'util';
import { buildPeripheralReadout, loadPeripheralReadout, peripheralCountsAtTime } from '../../../src/features/simulator/scene/peripheralReadout';

const bytes = fs.readFileSync(path.join(__dirname, '../../../public/assets/simulator/malecns/peripheral.json'));
const manifest = JSON.parse(bytes.toString('utf8'));
function fixture() {
  const input = manifest.rows.findIndex(row => row[1] === 'front_left' && row[2] === 'sensory');
  const output = manifest.rows.findIndex(row => row[1] === 'abdomen' && row[2] === 'motor');
  return { description: { dataset_id: manifest.dataset_id, annotations_sha256: manifest.annotations_sha256 },
    node_ids: BigUint64Array.from(manifest.rows.map(row => BigInt(row[0]))),
    spike_neurons: Int32Array.from([input, output]), spike_times_ms: Float32Array.from([30, 43]) };
}

test('nerve readout follows exact recorded cells, has no future activity and rewinds without mutating events', () => {
  const data = fixture(), saved = Buffer.from(data.spike_times_ms.buffer).toString('hex');
  const readout = buildPeripheralReadout(manifest, data);
  expect(readout.cells).toBe(10446);
  expect(peripheralCountsAtTime(readout, 'front_left', 29)).toEqual([0, 0]);
  expect(peripheralCountsAtTime(readout, 'front_left', 30)).toEqual([1, 0]);
  expect(peripheralCountsAtTime(readout, 'front_right', 30)).toEqual([0, 0]);
  expect(peripheralCountsAtTime(readout, 'abdomen', 42)).toEqual([0, 0]);
  expect(peripheralCountsAtTime(readout, 'abdomen', 43)).toEqual([0, 1]);
  expect(peripheralCountsAtTime(readout, 'abdomen', 49)).toEqual([0, 0]);
  expect(peripheralCountsAtTime(readout, 'front_left', 30)).toEqual([1, 0]);
  expect(Buffer.from(data.spike_times_ms.buffer).toString('hex')).toBe(saved);
  expect(peripheralCountsAtTime(null, 'abdomen', 43)).toEqual([0, 0]);
});

test('wrong dataset, missing source IDs and inconsistent coverage fail closed', () => {
  const data = fixture();
  expect(() => buildPeripheralReadout({ ...manifest, dataset_id: 'other' }, data)).toThrow('identity');
  data.node_ids[0] = 0n;
  expect(() => buildPeripheralReadout(manifest, data)).toThrow('node');
  expect(() => buildPeripheralReadout({ ...manifest, counts: {} }, fixture())).toThrow('coverage');
});

test('canonical source asset verifies its exact digest and rejects a corrupted byte', async () => {
  expect(bytes.includes(Buffer.from('\r\n'))).toBe(false);
  const oldFetch = global.fetch, oldCrypto = Object.getOwnPropertyDescriptor(global, 'crypto'), oldDecoder = global.TextDecoder;
  let body = Uint8Array.from(bytes);
  Object.defineProperty(global, 'crypto', { value: webcrypto, configurable: true }); global.TextDecoder = TextDecoder;
  global.fetch = jest.fn(async () => ({ ok: true, arrayBuffer: async () => body.buffer }));
  try {
    expect((await loadPeripheralReadout(fixture())).cells).toBe(10446);
    body = Uint8Array.from(body); body[10] ^= 1;
    await expect(loadPeripheralReadout(fixture())).rejects.toThrow('peripheral_integrity');
  } finally {
    global.fetch = oldFetch; global.TextDecoder = oldDecoder;
    if (oldCrypto) Object.defineProperty(global, 'crypto', oldCrypto); else delete global.crypto;
  }
});
