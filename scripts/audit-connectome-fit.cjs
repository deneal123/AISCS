const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const THREE = require('three');
const base = path.join(__dirname, '../public/assets/simulator/') + path.sep;
const scene = JSON.parse(fs.readFileSync(base + 'flybody/scene.json'));
const blob = fs.readFileSync(base + 'flybody/scene.bin');
const region = process.env.AISCS_CHECK_REGION || 'head';
const phase = Number(process.env.AISCS_SAMPLE_PHASE || '.5');
const meshes = (region === 'head' ? ['head', 'head_red', 'head_black'] : ['thorax']).map(name => {
  const part = scene.parts.find(item => item.name === name);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(blob.buffer.slice(blob.byteOffset + part.positions.byte_offset, blob.byteOffset + part.positions.byte_offset + part.positions.count * 4)), 3));
  geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(blob.buffer.slice(blob.byteOffset + part.indices.byte_offset, blob.byteOffset + part.indices.byte_offset + part.indices.count * 4)), 1));
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({side: THREE.DoubleSide}));
  mesh.updateMatrixWorld(true); return mesh;
});
const raw = zlib.gunzipSync(fs.readFileSync(base + `malecns/arbors-${region}.bin.gz`));
const boundaries = meshes.map(mesh => {
  const indices = mesh.geometry.index.array, edges = new Map();
  for (let i = 0; i < indices.length; i += 3) for (const [a, b] of [[indices[i], indices[i+1]], [indices[i+1], indices[i+2]], [indices[i+2], indices[i]]]) {
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    edges.set(key, (edges.get(key) || 0) + 1);
  }
  return [...edges.values()].filter(value => value !== 2).length;
});
const count = raw.length / 16, raycaster = new THREE.Raycaster();
const runtime = fs.readFileSync(path.join(__dirname, '../src/features/simulator/connectomeMorphology.js'), 'utf8');
const runtimeScale = runtime.match(/const BODY_VIEW_X_SCALE\s*=\s*([.\d]+)\s*;/);
const runtimeAngle = runtime.match(/const BODY_VIEW_ANGLE\s*=\s*([.\d]+)\s*;/);
const runtimeShift = runtime.match(/const BODY_VIEW_SHIFT_Z\s*=\s*([-.\d]+)\s*;/);
const runtimePivot = runtime.match(/const BODY_VIEW_PIVOT_X\s*=\s*([.\d]+),\s*BODY_VIEW_PIVOT_Z\s*=\s*([-\.\d]+)\s*;/);
if (!runtimeScale || !runtimeAngle || !runtimeShift || !runtimePivot) throw Error('Cannot identify runtime view transform');
const scaleX = Number(process.env.AISCS_VIEW_X_SCALE || runtimeScale[1]);
const offsetX = Number(process.env.AISCS_VIEW_X_OFFSET || '0');
const angle = Number(process.env.AISCS_VIEW_ANGLE || runtimeAngle[1]);
const shiftZ = Number(process.env.AISCS_VIEW_Z_OFFSET ?? runtimeShift[1]);
const pivotX = Number(runtimePivot[1]), pivotZ = Number(runtimePivot[2]);
let outside = 0, examples = [];
for (let i = 0; i < 1000; i++) {
  const offset = Math.floor((i + phase) * count / 1000) * 16;
  const x = raw.readFloatLE(offset), y = raw.readFloatLE(offset + 4), z = raw.readFloatLE(offset + 8);
  const baseX = scaleX * (.98 - (z - 180) * .00165) + offsetX, baseZ = .04 - (y - 200) * .0009;
  const dx = baseX - pivotX, dz = baseZ - pivotZ;
  const point = new THREE.Vector3(pivotX + Math.cos(angle) * dx + Math.sin(angle) * dz,
    (x - 393) * .001, pivotZ - Math.sin(angle) * dx + Math.cos(angle) * dz + shiftZ);
  const directions = [new THREE.Vector3(1, .001, .002).normalize(), new THREE.Vector3(.001, 1, .002).normalize(), new THREE.Vector3(.001, .002, 1).normalize()];
  const votes = directions.filter(direction => {
    raycaster.set(point, direction);
    return meshes.some(mesh => raycaster.intersectObject(mesh, false).length % 2 === 1);
  }).length;
  const inside = votes >= 2;
  if (!inside) { outside++; if (examples.length < 4) examples.push(point.toArray()); }
}
console.log(JSON.stringify({region, phase, scaleX, offsetX, angle, shiftZ, sample:1000, outside, examples, boundaries, caveat:'three-direction ray parity majority on separate meshes; index boundary counts do not weld duplicated vertices'}));
