import { Matrix4, Vector3 } from 'three';

const SCENE = '8eb70a265a179e811c902fda4334aa83bc34f54a58d400db0c3a6f98ccbd62dd';
const SOURCE = '35541d5312f71e7c96156c345cd90918867513a2b3dafbb07b8684ee59b6f4dc';
const DIGEST = '848804eae147fbfd30af36f1c5f406446b3850bda7f13f4ed81783f7c4cbd5ea';
const finite = (values, size) => Array.isArray(values) && values.length === size && values.every(Number.isFinite);
const matrix = values => {
  if (!finite(values, 16) || values.slice(12).some((value, index) => value !== (index === 3 ? 1 : 0))) throw new Error('rig_matrix');
  return new Matrix4().set(...values);
};

export function buildFlyKinematics(manifest) {
  if (manifest.format !== 'aspa.flybody.kinematics' || manifest.version !== 1
    || manifest.mesh_asset_sha256 !== SCENE || manifest.source_xml_sha256 !== SOURCE
    || manifest.units?.position !== 'mm' || manifest.units?.angle !== 'rad'
    || manifest.matrix_layout !== 'row-major 4x4; column-vector transform'
    || manifest.bodies?.length !== 68 || manifest.joints?.length !== 102
    || Object.keys(manifest.parts || {}).length !== 85) throw new Error('rig_identity');
  const joints = new Map(), names = new Map();
  for (const joint of manifest.joints) {
    if (joints.has(joint.name) || !finite(joint.axis, 3) || Math.abs(Math.hypot(...joint.axis) - 1) > 1e-8
      || !finite(joint.position_mm, 3) || !finite(joint.range_rad, 2)
      || !Number.isFinite(joint.rest_rad) || !Number.isFinite(joint.reference_rad)) throw new Error('rig_joint');
    joints.set(joint.name, { ...joint, axisVector: new Vector3(...joint.axis),
      before: new Matrix4().makeTranslation(...joint.position_mm),
      after: new Matrix4().makeTranslation(...joint.position_mm.map(value => -value)) });
  }
  const bodies = manifest.bodies.map((body, index) => {
    if (names.has(body.name) || (index === 0 ? body.parent !== null : !Number.isInteger(body.parent) || body.parent < 0 || body.parent >= index)
      || !Array.isArray(body.joints) || body.joints.some(name => joints.get(name)?.body !== body.name)) throw new Error('rig_hierarchy');
    names.set(body.name, index);
    return { ...body, base: matrix(body.base_local), rest: matrix(body.rest_world), inverseRest: matrix(body.rest_world).invert() };
  });
  if (Object.values(manifest.parts).some(name => !names.has(name))) throw new Error('rig_part');
  function pose(angles = {}) {
    for (const [name, value] of Object.entries(angles)) {
      const joint = joints.get(name);
      if (!joint || !Number.isFinite(value) || (joint.limited && (value < joint.range_rad[0] || value > joint.range_rad[1]))) throw new Error('rig_command');
    }
    const world = [], delta = [], anchors = new Map();
    const rotation = new Matrix4();
    bodies.forEach((body, index) => {
      const transform = body.free_root ? body.rest.clone() : index ? world[body.parent].clone().multiply(body.base) : body.base.clone();
      for (const name of body.joints) {
        const joint = joints.get(name);
        anchors.set(name, new Vector3(...joint.position_mm).applyMatrix4(transform));
        transform.multiply(joint.before).multiply(rotation.makeRotationAxis(joint.axisVector,
          (angles[name] ?? joint.rest_rad) - joint.reference_rad)).multiply(joint.after);
      }
      world.push(transform); delta.push(transform.clone().multiply(body.inverseRest));
    });
    return { world, delta, anchors,
      partMatrix: name => { const body = names.get(manifest.parts[name]); if (body === undefined) throw new Error('rig_part'); return delta[body]; },
    };
  }
  const neutral = pose();
  if (neutral.world.some((value, index) => value.elements.some((number, at) => Math.abs(number - bodies[index].rest.elements[at]) > 1e-8))) throw new Error('rig_rest_pose');
  return { bodies, joints, names, parts: manifest.parts, pose, neutral };
}

export async function loadFlyKinematics(signal) {
  const response = await fetch('/assets/simulator/flybody/rig.json', { signal });
  if (!response.ok) throw new Error('rig_unavailable');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== 56739) throw new Error('rig_size');
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== DIGEST) throw new Error('rig_integrity');
  return buildFlyKinematics(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
}
