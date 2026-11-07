// Search a bounded set of neighbouring native-EM points. A returned point is
// accepted only after the server screened it against the complete SWC index.
const keys = ['source_um', 'return_um', 'electrode_um', 'reference_um'];
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));

function blockedIndices(report, count) {
  if (!Array.isArray(report?.potential_intersections)) throw new Error('invalid_contact_screen');
  const blocked = new Set();
  for (const row of report.potential_intersections) {
    if (!Array.isArray(row?.contact_indices) || !row.contact_indices.length
        || row.contact_indices.some(i => !Number.isInteger(i) || i < 0 || i >= count)) throw new Error('invalid_contact_screen');
    row.contact_indices.forEach(i => blocked.add(i));
  }
  return blocked;
}

export async function resolveContactClearance(simulation, initialReport, screenPositions, isCurrent) {
  const original = keys.map(key => simulation[key].map(Number));
  const affected = blockedIndices(initialReport, 4);
  if (!affected.size) return { simulation, adjustments: [] };
  const options = original.map((point, i) => affected.has(i) ? [] : [point]);
  for (const distances of [[10, 25], [50, 100]]) {
    const candidates = [];
    for (const i of affected) for (const delta of distances) for (let axis = 0; axis < 3; axis++) for (const sign of [-1, 1]) {
      const point = [...original[i]]; point[axis] += delta * sign;
      candidates.push({ index: i, point, delta });
    }
    const report = await screenPositions(candidates.map(candidate => candidate.point));
    if (!isCurrent()) throw new Error('contact_draft_changed');
    const blocked = blockedIndices(report, candidates.length);
    candidates.forEach((candidate, index) => { if (!blocked.has(index)) options[candidate.index].push(candidate.point); });
    const selected = [null, null, null, null];
    for (const [left, right] of [[0, 1], [2, 3]]) {
      let best = null;
      for (const a of options[left]) for (const b of options[right]) {
        if (distance(a, b) <= 2 * simulation.clearance_um) continue;
        const score = distance(a, original[left]) + distance(b, original[right]);
        if (!best || score < best.score) best = { a, b, score };
      }
      if (best) { selected[left] = best.a; selected[right] = best.b; }
    }
    if (selected.length === 4 && selected.every(Boolean)) {
      const adjusted = { ...simulation, ...Object.fromEntries(keys.map((key, i) => [key, selected[i]])) };
      const adjustments = [...affected].map(i => ({ index: i, distance_um: distance(selected[i], original[i]) }));
      return { simulation: adjusted, adjustments };
    }
  }
  return null;
}
