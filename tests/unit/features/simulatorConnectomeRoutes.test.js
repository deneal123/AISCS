import { buildConnectomeRoutes, connectomeCoverage, mixSkin } from '../../../src/features/simulator/connectome/connectomeRoutes';

function fixture() {
  return {
    node_ids: new BigUint64Array([1n, 2n, 3n]),
    positions_mm: new Float32Array([.75, .04, .02, .1, 1.01, -1, -.1, -1.01, -1]),
    coordinate_kind: new Uint8Array([1, 0, 0]), regions: new Uint8Array([0, 1, 2]),
    edge_pre: new Uint32Array([1, 0, 1]), edge_post: new Uint32Array([0, 2, 2]),
    description: { scene: { regions: ['brain', 'front_left', 'front_right'], routes_mm: {
      front_left: [[0, 0, 0], [0, .2, 0], [.4, .4, -.4], [.1, 1, -1]],
      front_right: [[0, 0, 0], [0, -.2, 0], [-.4, -.4, -.4], [-.1, -1, -1]],
    } } },
  };
}
const row = (result, edge, i) => Array.from(result.atlas.subarray((result.starts[edge] + i) * 4, (result.starts[edge] + i) * 4 + 4));
const near = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));

test('peripheral edges visit the knee and body root instead of cutting directly across space', () => {
  const data = fixture(), original = new Float32Array(data.positions_mm), result = buildConnectomeRoutes(data);
  const path = Array.from({ length: result.steps[0] + 1 }, (_, i) => row(result, 0, i));
  expect(Math.min(...path.map(p => near(p.slice(0, 3), [.4, .4, -.4])))).toBeLessThan(.03);
  expect(Math.min(...path.map(p => near(p.slice(0, 3), [0, .2, 0])))).toBeLessThan(.03);
  expect([...data.positions_mm]).toEqual([...original]);
  expect([...result.positions.slice(0, 3)]).toEqual([...original.slice(0, 3)]);
  expect(result.skin[0]).toBe(-1);
  expect(near([...result.positions.slice(3, 6)], [.1, 1, -1])).toBeLessThan(.0021);
  expect(result.samples).toBeGreaterThan(data.edge_pre.length * 6);
});

test('pulse atlas and every drawn segment share exact vertices, endpoints and pose weights', () => {
  const data = fixture(), result = buildConnectomeRoutes(data);
  let line = 0;
  for (let e = 0; e < data.edge_pre.length; e += 1) {
    expect(row(result, e, 0).slice(0, 3)).toEqual([...result.positions.slice(data.edge_pre[e] * 3, data.edge_pre[e] * 3 + 3)]);
    expect(row(result, e, result.steps[e]).slice(0, 3)).toEqual([...result.positions.slice(data.edge_post[e] * 3, data.edge_post[e] * 3 + 3)]);
    for (let i = 0; i < result.steps[e]; i += 1) {
      const a = row(result, e, i), b = row(result, e, i + 1);
      expect([...result.linePositions.slice(line * 6, line * 6 + 6)]).toEqual([...a.slice(0, 3), ...b.slice(0, 3)]);
      expect([...result.lineSkin.slice(line * 2, line * 2 + 2)]).toEqual([a[3], b[3]]);
      expect(a.every(Number.isFinite) && b.every(Number.isFinite)).toBe(true);
      line += 1;
    }
  }
  expect(line).toBe(result.segments);
  expect(Math.max(result.width, result.height)).toBeLessThanOrEqual(2048);
});

test('a source-positioned neuron tagged for a leg remains a stationary CNS soma', () => {
  const data = fixture(); data.coordinate_kind[1] = 1;
  const result = buildConnectomeRoutes(data);
  expect([...result.positions.slice(3, 6)]).toEqual([...data.positions_mm.slice(3, 6)]);
  expect(result.skin[1]).toBe(-1);
  expect(mixSkin(-1, 1, 0)).toBe(-1);
  expect(mixSkin(-1, 1, .5)).toBe(.5);
  expect(mixSkin(1, -1, 1)).toBe(-1);
});

test('missing CNS positions never become a fallback plate or fabricated connections', () => {
  const data = fixture();
  data.coordinate_kind[0] = 0;
  data.positions_mm.set([.84, .2, .02], 0);
  const original = new Float32Array(data.positions_mm), result = buildConnectomeRoutes(data);
  expect(result.visibleNodes).toEqual([1, 2]);
  expect(result.visibleEdges).toEqual([2]);
  expect(result.steps[0]).toBe(0);
  expect(result.steps[1]).toBe(0);
  expect(result.steps[2]).toBeGreaterThan(0);
  expect(connectomeCoverage(data)).toEqual({ source: 0, neurite: 0, schematic: 2, hidden: 1 });
  expect([...data.positions_mm]).toEqual([...original]);
  expect([...result.atlas].every(Number.isFinite)).toBe(true);
  expect(result.segments).toBe(result.steps[2]);
});

test('unlocated CNS-only data remains an empty view instead of inventing anatomical positions', () => {
  const data = fixture();
  data.coordinate_kind.fill(0); data.regions.fill(0);
  const result = buildConnectomeRoutes(data);
  expect(result.visibleNodes).toEqual([]);
  expect(result.visibleEdges).toEqual([]);
  expect(result.samples).toBe(0);
  expect(result.linePositions.length).toBe(0);
  expect(connectomeCoverage(data)).toEqual({ source: 0, neurite: 0, schematic: 0, hidden: 3 });
  expect([...result.atlas].every(Number.isFinite)).toBe(true);
});
