import { createHash, webcrypto } from 'crypto';
import { TextEncoder } from 'util';
import { decodeSelectedMorphology } from '../../../src/features/simulator/connectome/selectedMorphology';

const raw = '1 0 0 0 0 1 -1\n2 0 125 0 0 1 1\n';
const record = text => ({ body_id: '42', manifest_sha256: 'graph',
  dataset_id: 'male-cns:v1.0-annotated-nonglial', source_units: '8 nm',
  source: 'https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation/skeletons-malecns/skeletons-swc/42.swc',
  sha256: createHash('sha256').update(text).digest('hex'), swc: text, vertices: 2 });

beforeAll(() => {
  Object.defineProperty(global, 'crypto', { configurable: true, value: webcrypto });
  global.TextEncoder = TextEncoder;
});

test('source coordinates are verified and converted into one source segment', async () => {
  const result = await decodeSelectedMorphology(record(raw), '42', 'graph');
  expect(result.vertices).toBe(2);
  expect(result.positions).toHaveLength(6);
});

test('mismatched graph and altered bytes cannot be shown as verified morphology', async () => {
  await expect(decodeSelectedMorphology(record(raw), '42', 'other')).rejects.toThrow('morphology_identity');
  await expect(decodeSelectedMorphology({ ...record(raw), swc: raw + ' ' }, '42', 'graph')).rejects.toThrow('morphology_hash');
});

test('missing parent is rejected even when source bytes have a matching hash', async () => {
  await expect(decodeSelectedMorphology(record(raw.replace(' 1\n', ' 3\n')), '42', 'graph'))
    .rejects.toThrow('morphology_parent');
});

test('cyclic reconstruction is rejected even when its checksum is valid', async () => {
  const cyclic = '1 0 0 0 0 1 2\n2 0 125 0 0 1 1\n';
  await expect(decodeSelectedMorphology(record(cyclic), '42', 'graph')).rejects.toThrow('morphology_cycle');
});
