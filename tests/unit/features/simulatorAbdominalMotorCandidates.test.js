import fs from 'fs';
import path from 'path';
import { abdominalMotorIndices, ABDOMINAL_MOTOR_GRAPH, ABDOMINAL_MOTOR_INVENTORY } from '../../../src/features/simulator/connectome/abdominalMotorCandidates';

const graph = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
const ASSET = path.join(__dirname, '../../../public/assets/simulator/malecns/abdominal-motors.json');

test('the abdominal motor layer follows the pinned graph and needs a soma position', () => {
  expect(ABDOMINAL_MOTOR_GRAPH).toBe(graph);
  const data = { description: { manifest_sha256: graph }, node_ids: [800664n, 42n, 906520n], coordinate_kind: [1, 1, 0] };
  expect(abdominalMotorIndices(data)).toEqual([0]);
  expect(abdominalMotorIndices({ ...data, description: { manifest_sha256: 'other' } })).toEqual([]);
  expect(abdominalMotorIndices(null)).toEqual([]);
  expect(abdominalMotorIndices({ ...data, node_ids: [42n], coordinate_kind: [1] })).toEqual([]);
});

test('the twenty recruited cells are named in the layer and exist in the published asset', () => {
  const asset = JSON.parse(fs.readFileSync(ASSET, 'utf8'));
  const published = new Set(asset.cells.map(cell => cell.id));
  expect(ABDOMINAL_MOTOR_INVENTORY.recruited).toHaveLength(20);
  for (const id of ABDOMINAL_MOTOR_INVENTORY.recruited) expect(published.has(id)).toBe(true);
  expect(ABDOMINAL_MOTOR_INVENTORY.neurons).toBe(307);
  expect(ABDOMINAL_MOTOR_INVENTORY.source_asset_sha256).toBe('9654b6ecc15faec066d77b3ec003fe379ff775272902eb1c0e0ea5680113be71');
});
