import fs from 'fs';
import path from 'path';
import { webcrypto } from 'crypto';
import { TextDecoder } from 'util';
import { loadAbdominalMotorInventory, recruitedWithin, ABDOMINAL_MOTOR_BYTES,
  ABDOMINAL_NEUROMERES, ABDOMINAL_NERVES } from '../../../src/features/simulator/scene/abdominalMotorReadout';

const ASSET = path.join(__dirname, '../../../public/assets/simulator/malecns/abdominal-motors.json');

test('the abdominal motor inventory is published as LF, verifies its digest and rejects corruption', async () => {
  const bytes = fs.readFileSync(ASSET);
  expect(bytes.includes(Buffer.from('\r\n'))).toBe(false);
  expect(bytes.byteLength).toBe(ABDOMINAL_MOTOR_BYTES);
  const previousFetch = global.fetch, previousCrypto = Object.getOwnPropertyDescriptor(global, 'crypto');
  const previousDecoder = global.TextDecoder;
  let body = Uint8Array.from(bytes);
  Object.defineProperty(global, 'crypto', { value: webcrypto, configurable: true });
  global.TextDecoder = TextDecoder;
  global.fetch = jest.fn(async () => ({ ok: true, arrayBuffer: async () => body.buffer }));
  try {
    const inventory = await loadAbdominalMotorInventory();
    expect(inventory.neurons).toBe(307);
    const bySubclass = inventory.countsBySubclass;
    expect(bySubclass.ad + bySubclass.wm + bySubclass.hm + bySubclass.hl + bySubclass.xm).toBe(307);
    const placed = ABDOMINAL_NERVES.reduce((total, nerve) => total + inventory.byNerve[nerve].length, 0);
    expect(placed).toBe(307);
    for (const neuromere of ABDOMINAL_NEUROMERES) expect(inventory.byNeuromere[neuromere].length).toBeGreaterThan(0);
    const grouped = Object.values(inventory.byNeuromere).reduce((total, ids) => total + ids.length, 0);
    expect(grouped).toBe(307);
    expect(inventory.notAMuscleModel).toBe(true);
    body = Uint8Array.from(body); body[10] ^= 1;
    await expect(loadAbdominalMotorInventory()).rejects.toThrow('abdominal_motor_integrity');
  } finally {
    global.fetch = previousFetch;
    global.TextDecoder = previousDecoder;
    if (previousCrypto) Object.defineProperty(global, 'crypto', previousCrypto);
    else delete global.crypto;
  }
});

test('every motor neuron the nociception sweep recruited is present in the inventory', () => {
  const manifest = JSON.parse(fs.readFileSync(ASSET, 'utf8'));
  const byNerve = Object.fromEntries(ABDOMINAL_NERVES.map(name => [name, []]));
  for (const cell of manifest.cells) byNerve[cell.exit_nerve].push(cell.id);
  const result = recruitedWithin({ byNerve });
  expect(result.expected).toBe(20);
  expect(result.missing).toEqual([]);
  expect(result.present).toBe(20);
});
