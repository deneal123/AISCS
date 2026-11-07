import fs from 'fs';
import path from 'path';
import { webcrypto } from 'crypto';
import { TextDecoder } from 'util';
import { loadMotorReadout } from '../../../src/features/simulator/scene/motorReadout';

test('published motor asset survives LF checkout, verifies its pinned digest and rejects corruption', async () => {
  const bytes = fs.readFileSync(path.join(__dirname, '../../../public/assets/simulator/malecns/motor.json'));
  expect(bytes.includes(Buffer.from('\r\n'))).toBe(false);
  const manifest = JSON.parse(bytes.toString('utf8'));
  const data = { description: { dataset_id: manifest.dataset_id, annotations_sha256: manifest.annotations_sha256 },
    node_ids: BigUint64Array.from(manifest.cells.map(cell => BigInt(cell.id))),
    spike_neurons: new Int32Array(), spike_times_ms: new Float32Array() };
  const previousFetch = global.fetch, previousCrypto = Object.getOwnPropertyDescriptor(global, 'crypto');
  const previousDecoder = global.TextDecoder;
  let body = Uint8Array.from(bytes);
  Object.defineProperty(global, 'crypto', { value: webcrypto, configurable: true });
  global.TextDecoder = TextDecoder;
  global.fetch = jest.fn(async () => ({ ok: true, arrayBuffer: async () => body.buffer }));
  try {
    const readout = await loadMotorReadout(data);
    expect(readout.events).toHaveLength(6);
    expect(readout.events.every(events => events.length === 0)).toBe(true);
    body = Uint8Array.from(body); body[10] ^= 1;
    await expect(loadMotorReadout(data)).rejects.toThrow('motor_integrity');
  } finally {
    global.fetch = previousFetch;
    global.TextDecoder = previousDecoder;
    if (previousCrypto) Object.defineProperty(global, 'crypto', previousCrypto);
    else delete global.crypto;
  }
});
