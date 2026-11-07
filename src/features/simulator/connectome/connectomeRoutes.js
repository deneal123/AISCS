// View-only nerve corridors, not recovered neurites or conductor geometry.
// Preserve measured CNS positions; only unmeasured peripheral glyphs are fitted
// to their declared body centre-line. IDs and the saved event journal never change.
export const ROUTING_VERSION = 'body-corridors-v1';
export const LEG_REGIONS = ['front_left', 'front_right', 'middle_left', 'middle_right', 'hind_left', 'hind_right'];
// Missing CNS coordinates cannot be inferred from connectivity. Legacy exports
// placed them on constant-X planes; never render those fallback coordinates as
// anatomy. Peripheral glyphs have explicit, separately labelled schematic routes.
export function hasDisplayPosition(data, i) {
  if (data.coordinate_kind?.[i] !== 0) return true;
  const name = data.description.scene.regions?.[data.regions?.[i]];
  return (data.description.scene.routes_mm?.[name]?.length || 0) >= 2;
}

export function connectomeCoverage(data) {
  let source = 0, neurite = 0, schematic = 0, hidden = 0;
  for (let i = 0; i < data.node_ids.length; i += 1) {
    if (!hasDisplayPosition(data, i)) hidden += 1;
    else if (data.coordinate_kind?.[i] === 0) schematic += 1;
    else if (data.coordinate_kind?.[i] === 3) neurite += 1;
    else source += 1;
  }
  return { source, neurite, schematic, hidden };
}
const TRUNK = [[-.58, 0, -.28], [-.377, 0, -.402], [-.144, 0, -.425], [.317, 0, -.272], [.54, 0, -.10], [.72, 0, .015], [.90, 0, .04]];
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const vertex = (p, skin = -1) => ({ p, skin });

// A nonnegative skin code packs leg * 2 + blend weight. The proximal root
// remains attached to the body while the distal path follows the leg's pose.
export function mixSkin(a, b, t) {
  if (a < 0 && b < 0) return -1;
  const legA = a < 0 ? -1 : Math.floor(a / 2), legB = b < 0 ? -1 : Math.floor(b / 2);
  if (legA >= 0 && legB >= 0 && legA !== legB) throw new Error('route_pose_boundary');
  const leg = Math.max(legA, legB);
  const weight = (a < 0 ? 0 : a - leg * 2) * (1 - t) + (b < 0 ? 0 : b - leg * 2) * t;
  return weight < 1e-8 ? -1 : leg * 2 + weight;
}

function project(p, path) {
  let nearest;
  for (let i = 0; i < path.length - 1; i += 1) {
    const a = path[i].p, b = path[i + 1].p, delta = b.map((v, j) => v - a[j]);
    const square = delta.reduce((sum, v) => sum + v * v, 0);
    const t = square ? Math.max(0, Math.min(1, delta.reduce((sum, v, j) => sum + (p[j] - a[j]) * v, 0) / square)) : 0;
    const q = mix(a, b, t), d = distance(p, q);
    if (!nearest || d < nearest.distance) nearest = { i, t, distance: d, node: vertex(q, mixSkin(path[i].skin, path[i + 1].skin, t)) };
  }
  return nearest;
}

function between(path, from, to) {
  if (from.i + from.t > to.i + to.t) return between(path, to, from).reverse();
  return [from.node, ...path.slice(from.i + 1, to.i + 1), to.node];
}

function compact(path) {
  return path.filter((v, i) => !i || distance(v.p, path[i - 1].p) > 1e-7);
}

// Round a corner locally, rather than fitting a global spline which can leave
// a thin limb. Bone boundaries retain their explicit body-attached root.
function rounded(path) {
  const clean = compact(path);
  if (clean.length < 3) return clean;
  const result = [clean[0]];
  for (let i = 1; i < clean.length - 1; i += 1) {
    const a = clean[i - 1], b = clean[i], c = clean[i + 1];
    if (a.skin !== b.skin || b.skin !== c.skin) { result.push(b); continue; }
    const before = distance(a.p, b.p), after = distance(b.p, c.p);
    const radius = Math.min(b.skin < 0 ? .035 : .012, before * .18, after * .18);
    const entry = mix(b.p, a.p, radius / before), exit = mix(b.p, c.p, radius / after);
    result.push(vertex(entry, b.skin));
    for (let step = 1; step <= 4; step += 1) {
      const t = step / 4;
      result.push(vertex(mix(mix(entry, b.p, t), mix(b.p, exit, t), t), b.skin));
    }
  }
  result.push(clean[clean.length - 1]);
  return compact(result);
}

function resample(path) {
  const points = rounded(path);
  if (points.length < 2) return [points[0], points[0]];
  const lengths = [0];
  for (let i = 1; i < points.length; i += 1) lengths.push(lengths[i - 1] + distance(points[i - 1].p, points[i].p));
  const total = lengths[lengths.length - 1], count = Math.max(6, Math.min(128, Math.ceil(total / .025) + 1));
  const result = []; let segment = 0;
  for (let i = 0; i < count; i += 1) {
    const at = total * i / (count - 1);
    while (segment < points.length - 2 && lengths[segment + 1] < at) segment += 1;
    const t = (at - lengths[segment]) / (lengths[segment + 1] - lengths[segment]);
    result.push(vertex(mix(points[segment].p, points[segment + 1].p, t), mixSkin(points[segment].skin, points[segment + 1].skin, t)));
  }
  return result;
}

export function bodyPath(points, name) {
  const leg = LEG_REGIONS.indexOf(name);
  return points.map((p, i) => vertex(p, i && leg >= 0 ? leg * 2 + 1 : -1));
}

export function buildConnectomeRoutes(data) {
  const paths = Object.fromEntries(Object.entries(data.description.scene.routes_mm || {}).map(([name, points]) => [name, bodyPath(points, name)]));
  const positions = new Float32Array(data.positions_mm), skin = new Float32Array(data.node_ids.length).fill(-1);
  const peripheral = new Map(), trunk = TRUNK.map(p => vertex(p));
  const visibleNodes = [], visibleEdges = [];
  for (let i = 0; i < data.node_ids.length; i += 1) {
    if (!hasDisplayPosition(data, i)) continue;
    visibleNodes.push(i);
    const name = data.description.scene.regions?.[data.regions?.[i]], path = paths[name];
    if (data.coordinate_kind?.[i] !== 0 || !path || path.length < 2) continue;
    const p = Array.from(positions.subarray(i * 3, i * 3 + 3)), projection = project(p, path);
    // Unmeasured glyphs may have a 12.5um lateral spread in old exports. Keep
    // their drawing within a small centre-line bundle, not floating beside a tarsus.
    const fitted = mix(projection.node.p, p, Math.min(.12, .002 / Math.max(projection.distance, 1e-9)));
    positions.set(fitted, i * 3); skin[i] = projection.node.skin;
    peripheral.set(i, { path, projection, name });
  }
  const endpoint = i => vertex(Array.from(positions.subarray(i * 3, i * 3 + 3)), skin[i]);
  const root = i => {
    const branch = peripheral.get(i), tip = endpoint(i);
    return branch ? [tip, ...between(branch.path, branch.projection, { i: 0, t: 0, node: branch.path[0] })] : [tip];
  };
  const edgeRoutes = [];
  let samples = 0, segments = 0;
  for (let e = 0; e < data.edge_pre.length; e += 1) {
    const pre = data.edge_pre[e], post = data.edge_post[e], a = peripheral.get(pre), b = peripheral.get(post);
    if (!hasDisplayPosition(data, pre) || !hasDisplayPosition(data, post)) {
      edgeRoutes.push([]); continue;
    }
    visibleEdges.push(e);
    let controls;
    if (a && b && a.name === b.name) {
      controls = [endpoint(pre), ...between(a.path, a.projection, b.projection), endpoint(post)];
    } else if (a || b || (positions[pre * 3] > .56) !== (positions[post * 3] > .56)) {
      const from = root(pre), to = root(post), p = from[from.length - 1], q = to[to.length - 1];
      controls = [...from, ...between(trunk, project(p.p, trunk), project(q.p, trunk)), ...to.reverse()];
    } else {
      const p = endpoint(pre), q = endpoint(post), middle = mix(p.p, q.p, .5);
      middle[2] += Math.min(.018, distance(p.p, q.p) * .12);
      controls = [p, vertex(middle), q];
    }
    const route = resample(controls);
    edgeRoutes.push(route); samples += route.length; segments += route.length - 1;
  }
  // <=128 samples * 24k display edges fits a 2048-square float texture.
  const width = Math.max(1, 2 ** Math.ceil(Math.log2(Math.sqrt(Math.max(1, samples))))), height = Math.max(1, Math.ceil(samples / width));
  const atlas = new Float32Array(width * height * 4), starts = new Float32Array(edgeRoutes.length), steps = new Float32Array(edgeRoutes.length);
  const linePositions = new Float32Array(segments * 6), lineSkin = new Float32Array(segments * 2);
  let offset = 0, line = 0;
  edgeRoutes.forEach((route, i) => {
    starts[i] = offset; steps[i] = Math.max(0, route.length - 1);
    route.forEach((v, j) => {
      atlas.set([...v.p, v.skin], (offset + j) * 4);
      if (j) {
        linePositions.set(route[j - 1].p, line * 6); linePositions.set(v.p, line * 6 + 3);
        lineSkin.set([route[j - 1].skin, v.skin], line * 2); line += 1;
      }
    });
    offset += route.length;
  });
  const guides = Object.fromEntries(Object.entries(paths).map(([name, path]) => [name, resample(path)]));
  return { positions, skin, atlas, width, height, starts, steps, linePositions, lineSkin, guides, samples, segments,
    visibleNodes, visibleEdges };
}
