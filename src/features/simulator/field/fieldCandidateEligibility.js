// Shared geometry and clearance rules for manual and automatic source selection.
export function candidateEligibility(row, simulation, excluded = new Set()) {
  const geometry = row?.geometry;
  const incompatible = !geometry || !['components', 'isolated_roots', 'zero_length_edges', 'nonpositive_radius_edges']
    .every(key => Number.isSafeInteger(geometry[key]) && geometry[key] >= (key === 'components' ? 1 : 0))
    || geometry.isolated_roots > 0 || geometry.zero_length_edges > 0
    || geometry.nonpositive_radius_edges > 0 || (geometry.components > 1 && !simulation.allow_disconnected);
  const clearance = row?.conservative_clearance_um;
  const recordingClearance = row?.recording_clearance_um;
  const validClearance = Array.isArray(clearance) && clearance.length === 2 && clearance.every(Number.isFinite);
  const validRecordingClearance = Array.isArray(recordingClearance) && recordingClearance.length === 2 && recordingClearance.every(Number.isFinite);
  const limit = Number(simulation.clearance_um);
  const tooClose = validClearance && Number.isFinite(limit) && clearance.some(value => value <= limit);
  const recordingTooClose = validRecordingClearance && Number.isFinite(limit) && recordingClearance.some(value => value <= limit);
  const unavailable = incompatible || !validClearance || !validRecordingClearance || tooClose || recordingTooClose
    || row?.isolated_root !== false || excluded.has(String(row.body_id))
    || !Number.isSafeInteger(row.body_id) || row.body_id <= 0 || !Number.isSafeInteger(row.child_node_id) || row.child_node_id <= 0
    || !Number.isFinite(row.edge_fraction) || row.edge_fraction < 0 || row.edge_fraction > 1;
  return { incompatible, tooClose, recordingTooClose, unavailable };
}
