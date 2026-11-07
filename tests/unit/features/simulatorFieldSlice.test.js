import { bipolarPotential, fieldSlice, stimulusAtTime } from '../../../src/features/simulator/field/fieldSlice';

test('ideal bipolar field has the correct sign, units and exclusion', () => {
  const source = [0, 0, 0], target = [100, 0, 0];
  const expected = 1000 / (4 * Math.PI * .3) * (1 / Math.hypot(25, 50) - 1 / Math.hypot(75, 50));
  expect(bipolarPotential([25, 50, 0], source, target, 1000, .3, 2)).toBeCloseTo(expected, 12);
  expect(bipolarPotential([75, 50, 0], source, target, 1000, .3, 2)).toBeCloseTo(-expected, 12);
  expect(bipolarPotential(source, source, target, 1000, .3, 2)).toBeNull();
  expect(bipolarPotential([25, 50, 0], source, target, 0, .3, 2)).toBe(0);
});

test('grid excludes cells crossing contacts and does not fabricate activity', () => {
  const simulation = { source_um: [0, 0, 0], return_um: [100, 0, 0], current_na: 1000,
    conductivity_s_m: .3, clearance_um: 5 };
  const slice = fieldSlice(simulation, 10);
  expect(slice.maximum).toBeGreaterThan(0);
  expect(slice.maximum).toBe(Math.max(...slice.triangles.map(index => Math.abs(slice.values[index]))));
  for (let i = 0; i < slice.triangles.length; i += 3) {
    const vertices = slice.triangles.slice(i, i + 3).map(index => slice.positions[index]);
    const xs = vertices.map(point => point[0]), ys = vertices.map(point => point[1]);
    [simulation.source_um, simulation.return_um].forEach(point => {
      const dx = Math.max(Math.min(...xs) - point[0], 0, point[0] - Math.max(...xs));
      const dy = Math.max(Math.min(...ys) - point[1], 0, point[1] - Math.max(...ys));
      expect(Math.hypot(dx, dy)).toBeGreaterThan(5);
    });
  }
  expect(fieldSlice({ ...simulation, current_na: 0 }, 10).maximum).toBe(0);
  expect(() => fieldSlice({ ...simulation, return_um: [1, 0, 0] })).toThrow();
});

test('playback interpolates signed stimulus samples on one timeline', () => {
  const preview = { time_ms: [0, 1, 2, 3], stimulus_fraction: [0, 1, -1, 0] };
  expect(stimulusAtTime(preview, .5)).toBe(.5);
  expect(stimulusAtTime(preview, 1.5)).toBe(0);
  expect(stimulusAtTime(preview, 2.5)).toBe(-.5);
  expect(stimulusAtTime(null, 1)).toBe(0);
});

test('all three planes keep the fixed native coordinate and respect both exclusion spheres', () => {
  const simulation = { source_um: [10, 20, 30], return_um: [110, 120, 130], current_na: 1000,
    conductivity_s_m: .3, clearance_um: 5 };
  [['xy', 2, 'Z'], ['xz', 1, 'Y'], ['yz', 0, 'X']].forEach(([plane, axis, label]) => {
    const slice = fieldSlice(simulation, 12, plane);
    expect(slice.fixedAxis).toBe(label);
    expect(slice.fixedValue).toBe((simulation.source_um[axis] + simulation.return_um[axis]) / 2);
    expect(slice.positions.every(point => point[axis] === slice.fixedValue)).toBe(true);
    slice.triangles.forEach(index => {
      const point = slice.positions[index];
      expect(Math.hypot(...point.map((value, i) => value - simulation.source_um[i]))).toBeGreaterThan(5);
      expect(Math.hypot(...point.map((value, i) => value - simulation.return_um[i]))).toBeGreaterThan(5);
    });
  });
  expect(() => fieldSlice(simulation, 12, 'wrong')).toThrow();
  const moved = fieldSlice(simulation, 12, 'xz', 37.25);
  expect(moved.fixedAxis).toBe('Y');
  expect(moved.positions.every(point => point[1] === 37.25)).toBe(true);
  expect(() => fieldSlice(simulation, 12, 'xy', Infinity)).toThrow();
});

test('mesh interpolation approaches the analytic field away from the contacts', () => {
  const simulation = { source_um: [0, 0, 0], return_um: [100, 0, 0], current_na: 1000,
    conductivity_s_m: .3, clearance_um: 5 };
  const measure = steps => {
    const slice = fieldSlice(simulation, steps);
    let squared = 0, count = 0;
    for (let i = 0; i < slice.triangles.length; i += 3) {
      const ids = slice.triangles.slice(i, i + 3), vertices = ids.map(index => slice.positions[index]);
      const center = [0, 1, 2].map(axis => vertices.reduce((sum, point) => sum + point[axis], 0) / 3);
      if ([simulation.source_um, simulation.return_um].some(contact => Math.hypot(...center.map((value, axis) => value - contact[axis])) < 30)) continue;
      const exact = bipolarPotential(center, simulation.source_um, simulation.return_um, 1000, .3, 5);
      const linear = ids.reduce((sum, index) => sum + slice.values[index], 0) / 3;
      squared += (linear - exact) ** 2; count += 1;
    }
    return Math.sqrt(squared / count);
  };
  expect(measure(96)).toBeLessThan(measure(48));
});

test('overview uses explicit native bounds in each plane', () => {
  const simulation = { source_um: [0, 0, 0], return_um: [100, 0, 0], current_na: 1000,
    conductivity_s_m: .3, clearance_um: 5 };
  const bounds = [[-300, 800], [-200, 900], [-100, 500]];
  [['xy', 0, 1], ['xz', 0, 2], ['yz', 1, 2]].forEach(([plane, u, v]) => {
    const slice = fieldSlice(simulation, 8, plane, null, bounds);
    expect(slice.positions[0][u]).toBe(bounds[u][0]);
    expect(slice.positions[0][v]).toBe(bounds[v][0]);
    expect(slice.positions.at(-1)[u]).toBe(bounds[u][1]);
    expect(slice.positions.at(-1)[v]).toBe(bounds[v][1]);
  });
  expect(() => fieldSlice(simulation, 8, 'xy', null, [[0, 0], [0, 1], [0, 1]])).toThrow();
});
