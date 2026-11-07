// Ideal bipolar point contacts in an infinite homogeneous medium. Coordinates
// are native MaleCNS micrometres; values are mV for the full-amplitude pulse.
export function bipolarPotential(point, source, target, current, conductivity, clearance) {
  const first = Math.hypot(...point.map((value, index) => value - source[index]));
  const second = Math.hypot(...point.map((value, index) => value - target[index]));
  if (first <= clearance || second <= clearance) return null;
  return current / (4 * Math.PI * conductivity) * (1 / first - 1 / second);
}

export function stimulusAtTime(preview, time) {
  const times = preview?.time_ms, values = preview?.stimulus_fraction;
  if (!Array.isArray(times) || !Array.isArray(values) || !times.length || times.length !== values.length || !Number.isFinite(time)) return 0;
  if (time <= times[0]) return values[0];
  if (time >= times.at(-1)) return values.at(-1);
  let low = 0, high = times.length - 1;
  while (high - low > 1) { const middle = Math.floor((low + high) / 2); if (times[middle] <= time) low = middle; else high = middle; }
  const fraction = (time - times[low]) / (times[high] - times[low]);
  return values[low] + fraction * (values[high] - values[low]);
}

export function fieldSlice(simulation, steps = 48, plane = 'xy', position = null, bounds = null) {
  const { source_um: source, return_um: target, current_na: current,
    conductivity_s_m: conductivity, clearance_um: clearance } = simulation || {};
  if (![source, target].every(point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite))
      || ![current, conductivity, clearance].every(Number.isFinite) || conductivity <= 0 || clearance <= 0
      || !Number.isInteger(steps) || steps < 2 || steps > 128 || !['xy', 'xz', 'yz'].includes(plane)
      || (position !== null && !Number.isFinite(position))
      || (bounds !== null && (!Array.isArray(bounds) || bounds.length !== 3 || !bounds.every(range => Array.isArray(range)
        && range.length === 2 && range.every(Number.isFinite) && range[0] < range[1])))
      || Math.hypot(...source.map((value, index) => value - target[index])) <= 2 * clearance) throw new Error('invalid_field_slice');
  const [u, v, fixed] = plane === 'xy' ? [0, 1, 2] : plane === 'xz' ? [0, 2, 1] : [1, 2, 0];
  const margin = Math.max(100, Math.hypot(...source.map((value, index) => value - target[index])) * .25);
  const minU = bounds ? bounds[u][0] : Math.min(source[u], target[u]) - margin;
  const maxU = bounds ? bounds[u][1] : Math.max(source[u], target[u]) + margin;
  const minV = bounds ? bounds[v][0] : Math.min(source[v], target[v]) - margin;
  const maxV = bounds ? bounds[v][1] : Math.max(source[v], target[v]) + margin;
  const fixedValue = position === null ? (source[fixed] + target[fixed]) / 2 : position;
  const positions = [], values = [], triangles = [];
  for (let y = 0; y <= steps; y += 1) for (let x = 0; x <= steps; x += 1) {
    const point = [0, 0, 0]; point[u] = minU + (maxU - minU) * x / steps;
    point[v] = minV + (maxV - minV) * y / steps; point[fixed] = fixedValue;
    const value = bipolarPotential(point, source, target, current, conductivity, clearance);
    if (!point.every(Number.isFinite) || (value !== null && !Number.isFinite(value))) throw new Error('invalid_field_slice');
    positions.push(point); values.push(value);
  }
  for (let y = 0; y < steps; y += 1) for (let x = 0; x < steps; x += 1) {
    const a = y * (steps + 1) + x, b = a + 1, c = a + steps + 1, d = c + 1;
    // A cell may intersect an exclusion sphere even if all four vertices are outside it.
    const excluded = [source, target].some(contact => {
      const du = Math.max(positions[a][u] - contact[u], 0, contact[u] - positions[b][u]);
      const dv = Math.max(positions[a][v] - contact[v], 0, contact[v] - positions[c][v]);
      return Math.hypot(du, dv, fixedValue - contact[fixed]) <= clearance;
    });
    if (excluded) continue;
    [[a, b, c], [b, d, c]].forEach(indices => { if (indices.every(index => values[index] !== null)) triangles.push(...indices); });
  }
  // Excluded cells may own large, unrendered vertex values. They must not set
  // the visible colour scale for the remainder of the slice.
  const maximum = triangles.reduce((result, index) => Math.max(result, Math.abs(values[index])), 0);
  return { positions, values, triangles, maximum, fixedAxis: ['X', 'Y', 'Z'][fixed], fixedValue };
}
