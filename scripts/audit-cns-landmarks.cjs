// Display-geometry diagnostic only. Region centroids are not attachment sites
// and do not establish an anatomical registration between different animals.
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const crypto = require('crypto');
const THREE = require('three');

const root = path.resolve(__dirname, '../..');
const base = path.join(root, '.data/male-cns/neuropil-lod-v1');
const manifest = JSON.parse(fs.readFileSync(path.join(base, 'manifest.json')));
if (manifest.dataset_id !== 'male-cns:v1.0-annotated-nonglial'
    || manifest.source_frame !== 'MaleCNS native unmirrored EM' || manifest.units !== 'um') throw new Error('Unexpected source identity');
const rig = JSON.parse(fs.readFileSync(path.join(root, 'frontend/public/assets/simulator/flybody/rig.json')));
const runtime = fs.readFileSync(path.join(root, 'frontend/src/features/simulator/connectomeMorphology.js'), 'utf8');
const value = name => {
  const match = runtime.match(new RegExp(`\\b${name}\\s*=\\s*([-+.\\d]+)`));
  if (!match) throw new Error(`Missing ${name}`);
  return Number(match[1]);
};
const scale = value('BODY_VIEW_X_SCALE'), angle = value('BODY_VIEW_ANGLE');
const shift = value('BODY_VIEW_SHIFT_Z'), pivotX = value('BODY_VIEW_PIVOT_X'), pivotZ = value('BODY_VIEW_PIVOT_Z');
const labels = ['LA(L)', 'LA(R)', 'ME(L)', 'ME(R)', 'LO(L)', 'LO(R)',
  ...[1, 2, 3].flatMap(i => [`LegNp(T${i})(L)`, `LegNp(T${i})(R)`]), 'ANm'];
const median = values => {
  values.sort((a, b) => a - b);
  const m = Math.floor(values.length / 2);
  return values.length % 2 ? values[m] : (values[m - 1] + values[m]) / 2;
};
const result = {};
for (const label of labels) {
  const item = manifest.meshes.find(mesh => mesh.label === label);
  if (!item) throw new Error(`Missing region ${label}`);
  if (item.file !== `${item.dataset}-${item.id}.bin.gz`) throw new Error(`Invalid filename for ${label}`);
  const compressed = fs.readFileSync(path.join(base, item.file));
  if (crypto.createHash('sha256').update(compressed).digest('hex') !== item.sha256) throw new Error(`Hash mismatch for ${label}`);
  const data = zlib.gunzipSync(compressed);
  if (data.readUInt32LE(0) !== item.vertices || data.length !== 8 + 12 * (item.vertices + item.triangles)) throw new Error(`Invalid ${label}`);
  const coords = [[], [], []];
  for (let i = 0; i < item.vertices; i++) {
    const p = 8 + i * 12;
    const a = data.readFloatLE(p), b = data.readFloatLE(p + 4), c = data.readFloatLE(p + 8);
    const x = scale * (.98 - (c - 180) * .00165), y = (a - 393) * .001, z = .04 - (b - 200) * .0009;
    const dx = x - pivotX, dz = z - pivotZ;
    const mapped = [pivotX + Math.cos(angle) * dx + Math.sin(angle) * dz, y,
      pivotZ - Math.sin(angle) * dx + Math.cos(angle) * dz + shift];
    if (!mapped.every(Number.isFinite)) throw new Error(`Invalid coordinates in ${label}`);
    mapped.forEach((v, axis) => coords[axis].push(v));
  }
  result[label] = { vertices: item.vertices, median_mm: coords.map(median) };
}
const parts = {};
for (const name of ['head', ...[1, 2, 3].flatMap(i => [`coxa_T${i}_left`, `coxa_T${i}_right`])]) {
  const body = rig.bodies.find(part => part.name === name);
  if (!body) throw new Error(`Missing body ${name}`);
  parts[name] = [body.rest_world[3], body.rest_world[7], body.rest_world[11]];
}
const assets = path.join(root, 'frontend/public/assets/simulator/flybody');
const sceneBytes = fs.readFileSync(path.join(assets, 'scene.json'));
if (crypto.createHash('sha256').update(sceneBytes).digest('hex') !== rig.mesh_asset_sha256) throw new Error('FlyBody scene hash mismatch');
const scene = JSON.parse(sceneBytes);
const sceneBlob = fs.readFileSync(path.join(assets, 'scene.bin'));
if (scene.binary?.file !== 'scene.bin' || sceneBlob.length !== scene.binary.bytes
    || crypto.createHash('sha256').update(sceneBlob).digest('hex') !== scene.binary.sha256) throw new Error('FlyBody mesh hash mismatch');
const eyePart = scene.parts.find(item => item.name === 'head_red');
if (!eyePart) throw new Error('Missing eye mesh');
const field = item => sceneBlob.buffer.slice(sceneBlob.byteOffset + item.byte_offset,
  sceneBlob.byteOffset + item.byte_offset + item.count * 4);
const eyeVertices = new Float32Array(field(eyePart.positions)), eyeIndices = new Uint32Array(field(eyePart.indices));
const triangle = new THREE.Triangle(), closest = new THREE.Vector3(), eyeDistances = {};
for (const side of ['L', 'R']) {
  eyeDistances[side] = {};
  for (const region of ['LA', 'ME', 'LO']) {
    const point = new THREE.Vector3(...result[`${region}(${side})`].median_mm);
    let minimum = Infinity;
    for (let i = 0; i < eyeIndices.length; i += 3) {
      [triangle.a, triangle.b, triangle.c].forEach((vertex, j) => vertex.fromArray(eyeVertices, eyeIndices[i + j] * 3));
      triangle.closestPointToPoint(point, closest);
      if ((side === 'L' && closest.y < 0) || (side === 'R' && closest.y > 0)) continue;
      minimum = Math.min(minimum, closest.distanceTo(point));
    }
    if (!Number.isFinite(minimum)) throw new Error(`Missing ${side} eye geometry`);
    eyeDistances[side][region] = minimum;
  }
}
const legX = i => (result[`LegNp(T${i})(L)`].median_mm[0] + result[`LegNp(T${i})(R)`].median_mm[0]) / 2;
const checks = { leg_neuropil_anterior_to_posterior: legX(1) > legX(2) && legX(2) > legX(3),
  coxa_anterior_to_posterior: parts.coxa_T1_left[0] > parts.coxa_T2_left[0] && parts.coxa_T2_left[0] > parts.coxa_T3_left[0],
  bilateral_left_right_consistent: [1, 2, 3].every(i => result[`LegNp(T${i})(L)`].median_mm[1] > result[`LegNp(T${i})(R)`].median_mm[1]
    && parts[`coxa_T${i}_left`][1] > parts[`coxa_T${i}_right`][1]),
  optic_regions_bilateral_order: ['LA', 'ME', 'LO'].every(name => result[`${name}(L)`].median_mm[1] > result[`${name}(R)`].median_mm[1]),
  optic_lamina_more_lateral_than_medulla: ['L', 'R'].every(side => Math.abs(result[`LA(${side})`].median_mm[1]) > Math.abs(result[`ME(${side})`].median_mm[1])),
  optic_lamina_median_closer_to_external_eye_mesh: ['L', 'R'].every(side => eyeDistances[side].LA < eyeDistances[side].ME) };
console.log(JSON.stringify({ source_frame: manifest.source_frame, rig_asset_sha256: rig.mesh_asset_sha256,
  transform: { scaleX: scale, angle, shiftZ_mm: shift, pivotX_mm: pivotX, pivotZ_mm: pivotZ },
  neuropil: result, body_anchors_mm: parts, optic_median_distance_to_eye_mesh_mm: eyeDistances, checks,
  limitation: 'Different specimens. Region medians and joint origins are not homologous landmarks; no positional accuracy or tissue registration is established.' }, null, 2));
if (Object.values(checks).some(pass => !pass)) process.exitCode = 1;
