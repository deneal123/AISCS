import { buildNeckMotorReadout, neckEventsAtTime } from '../../../src/features/simulator/scene/neckMotor';
import manifest from '../../../public/assets/simulator/malecns/neck-motor.json';

const source = 'd27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee';
const fixture = () => ({ node_ids: BigUint64Array.from(manifest.cells.map(cell => BigInt(cell.id))),
  spike_neurons: new Int32Array([0, 1, 0]), spike_times_ms: new Float32Array([10, 12, 30]),
  description: { dataset_id: manifest.dataset_id, annotations_sha256: source } });

test('cervical event readout is tied to registered IDs and follows the saved clock', () => {
  const readout = buildNeckMotorReadout(manifest, fixture());
  expect(readout.active).toBe(2); expect(readout.first).toBe(10);
  expect(neckEventsAtTime(readout, 9)).toBe(0);
  expect(neckEventsAtTime(readout, 12)).toBe(2);
  expect(neckEventsAtTime(readout, 30)).toBe(1);
  expect(neckEventsAtTime(readout, 9)).toBe(0);
});

test('foreign or incomplete annotations cannot produce neck events', () => {
  expect(() => buildNeckMotorReadout({ ...manifest, annotations_sha256: 'bad' }, fixture())).toThrow('neck_identity');
  expect(() => buildNeckMotorReadout(manifest, { ...fixture(), node_ids: new BigUint64Array() })).toThrow('neck_population');
});
