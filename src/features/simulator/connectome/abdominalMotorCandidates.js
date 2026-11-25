import inventory from './abdominalMotorCandidates.json';

// The abdominal motor neurons the nociception sweep recruited, drawn as rings on the
// pinned graph. This is an inventory of measured cells, not a muscle map: the
// connectome has no muscle nodes and a motor spike is not a contraction.
export const ABDOMINAL_MOTOR_GRAPH = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
const RECRUITED = new Set(inventory.recruited);

export function abdominalMotorIndices(data) {
  if (data?.description?.manifest_sha256 !== ABDOMINAL_MOTOR_GRAPH || !data.node_ids) return [];
  const indices = [];
  data.node_ids.forEach((id, index) => {
    if (RECRUITED.has(String(id)) && data.coordinate_kind?.[index] > 0) indices.push(index);
  });
  return indices;
}

export const ABDOMINAL_MOTOR_INVENTORY = inventory;
