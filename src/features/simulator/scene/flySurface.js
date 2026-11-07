// One Loop subdivision of the display surface. Registered source triangles
// remain separate: this aesthetic derivative never defines electrode physics.
export function smoothFlySurface(source) {
  const points = [], faces = [], lookup = new Map();
  for (let i = 0; i < source.length; i += 3) {
    const point = source.slice(i, i + 3);
    const key = point.map(value => Math.round(value * 1e7)).join(',');
    if (!lookup.has(key)) { lookup.set(key, points.length); points.push(point); }
    faces.push(lookup.get(key));
  }
  const neighbors = points.map(() => new Set()), edges = new Map();
  const edgeKey = (a, b) => a < b ? `${a}:${b}` : `${b}:${a}`;
  for (let i = 0; i < faces.length; i += 3) {
    const [a, b, c] = faces.slice(i, i + 3);
    [[a, b, c], [b, c, a], [c, a, b]].forEach(([u, v, opposite]) => {
      neighbors[u].add(v); neighbors[v].add(u);
      const key = edgeKey(u, v);
      if (!edges.has(key)) edges.set(key, { u, v, opposite: [] });
      edges.get(key).opposite.push(opposite);
    });
  }
  const boundary = points.map(() => []);
  edges.forEach(({ u, v, opposite }) => {
    if (opposite.length === 1) { boundary[u].push(v); boundary[v].push(u); }
  });
  const result = points.map((point, i) => {
    if (boundary[i].length === 2) return point.map((value, axis) => .75 * value + .125 * boundary[i].reduce((sum, neighbor) => sum + points[neighbor][axis], 0));
    if (boundary[i].length || neighbors[i].size < 3) return [...point];
    const count = neighbors[i].size, beta = count === 3 ? 3 / 16 : 3 / (8 * count);
    return point.map((value, axis) => (1 - count * beta) * value + beta * [...neighbors[i]].reduce((sum, neighbor) => sum + points[neighbor][axis], 0));
  });
  edges.forEach(edge => {
    edge.index = result.length;
    const { u, v, opposite } = edge;
    result.push(points[u].map((value, axis) => opposite.length === 2
      ? .375 * (value + points[v][axis]) + .125 * (points[opposite[0]][axis] + points[opposite[1]][axis])
      : .5 * (value + points[v][axis])));
  });
  const indices = [];
  for (let i = 0; i < faces.length; i += 3) {
    const [a, b, c] = faces.slice(i, i + 3);
    const ab = edges.get(edgeKey(a, b)).index, bc = edges.get(edgeKey(b, c)).index, ca = edges.get(edgeKey(c, a)).index;
    indices.push(a, ab, ca, b, bc, ab, c, ca, bc, ab, bc, ca);
  }
  return { positions: result.flat(), indices };
}
