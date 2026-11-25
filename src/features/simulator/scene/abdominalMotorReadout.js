// Abdominal motor inventory: the cells the nociception sweep actually recruited.
// This is an inventory, not a muscle model: a motor spike is not a contraction,
// and the connectome has no muscle nodes at all.
export const ABDOMINAL_MOTOR_VERSION = 'male-cns-abdominal-motor-inventory-v1';
export const ABDOMINAL_MOTOR_BYTES = 48510;
export const ABDOMINAL_MOTOR_SHA256 = '9654b6ecc15faec066d77b3ec003fe379ff775272902eb1c0e0ea5680113be71';
// A10 exists in the annotation, and some cells that leave through an abdominal nerve
// have a thoracic neuromere of their soma, so both keys are grouped as they come.
export const ABDOMINAL_NEUROMERES = ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'A10'];
export const UNPLACED = 'unplaced';
export const ABDOMINAL_NERVES = ['AbN1', 'AbN2', 'AbN3', 'AbN4', 'AbNT', 'ADMN', 'MesoAN', 'PDMNa', 'PDMNp'];
const SUBCLASSES = ['ad', 'wm', 'hm', 'hl', 'xm'];

export function buildAbdominalMotorInventory(manifest) {
  if (manifest.version !== ABDOMINAL_MOTOR_VERSION || !Array.isArray(manifest.cells)
    || manifest.neurons !== manifest.cells.length) throw new Error('abdominal_motor_identity');
  const byNeuromere = {};
  const byNerve = Object.fromEntries(ABDOMINAL_NERVES.map(name => [name, []]));
  for (const cell of manifest.cells) {
    if (typeof cell.id !== 'string' || !SUBCLASSES.includes(cell.subclass)) throw new Error('abdominal_motor_cell');
    if (!ABDOMINAL_NERVES.includes(cell.exit_nerve)) throw new Error('abdominal_motor_placement');
    byNerve[cell.exit_nerve].push(cell.id);
    const key = cell.neuromere || UNPLACED;
    (byNeuromere[key] ||= []).push(cell.id);
  }
  return { version: ABDOMINAL_MOTOR_VERSION, neurons: manifest.neurons,
    countsBySubclass: manifest.counts_by_subclass, countsByNerve: manifest.counts_by_nerve,
    byNeuromere, byNerve, laterality: 'soma-side-inventory-only',
    notAMuscleModel: true };
}

export async function loadAbdominalMotorInventory(signal) {
  const response = await fetch('/assets/simulator/malecns/abdominal-motors.json', { signal });
  if (!response.ok) throw new Error('abdominal_motor_unavailable');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== ABDOMINAL_MOTOR_BYTES) throw new Error('abdominal_motor_size');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
  if (digest !== ABDOMINAL_MOTOR_SHA256) throw new Error('abdominal_motor_integrity');
  return buildAbdominalMotorInventory(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
}

// Which of the measured cells are in the inventory. The twenty recruited motor neurons
// come from a forced network and a real pass; naming them here keeps the two datasets
// from drifting apart without anyone noticing.
export const RECRUITED_MOTOR_IDS = ['800608', '800659', '800664', '800696', '800743', '800762',
  '801158', '801304', '801394', '801434', '801899', '802251', '802252', '802500',
  '803904', '804173', '804966', '805107', '903679', '906520'];

export function recruitedWithin(inventory) {
  const known = new Set(inventory.byNerve[ABDOMINAL_NERVES[0]].concat(...ABDOMINAL_NERVES.slice(1).map(n => inventory.byNerve[n])));
  const present = RECRUITED_MOTOR_IDS.filter(id => known.has(id));
  return { present: present.length, expected: RECRUITED_MOTOR_IDS.length, missing: RECRUITED_MOTOR_IDS.filter(id => !known.has(id)) };
}
