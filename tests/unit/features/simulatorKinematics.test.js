import fs from 'fs';
import path from 'path';
import { Matrix4 } from 'three';
import { buildFlyKinematics } from '../../../src/features/simulator/scene/flyKinematics';

const rig = JSON.parse(fs.readFileSync(path.join(__dirname, '../../../public/assets/simulator/flybody/rig.json'), 'utf8'));
const references = JSON.parse(fs.readFileSync(path.join(__dirname, '../../fixtures/simulator/flybody-kinematics-reference.json'), 'utf8'));

test.each(references.cases)('all body frames and hinge anchors match MuJoCo: $name', sample => {
  const model = buildFlyKinematics(rig), pose = model.pose(sample.angles_rad);
  model.bodies.forEach((body, i) => {
    const expected = new Matrix4().set(...sample.world[body.name]);
    expect(Math.max(...pose.world[i].elements.map((value, at) => Math.abs(value - expected.elements[at])))).toBeLessThan(1e-8);
  });
  for (const [name, anchor] of pose.anchors) {
    expect(Math.max(...anchor.toArray().map((value, at) => Math.abs(value - sample.anchors_mm[name][at])))).toBeLessThan(1e-8);
  }
});

test('head, eyes and antenna parents move together while the thorax and mesh coordinates stay fixed', () => {
  const saved = JSON.stringify(rig), model = buildFlyKinematics(rig), pose = model.pose({ head_abduct: .1 });
  expect(pose.partMatrix('head').equals(pose.partMatrix('head_red'))).toBe(true);
  expect(pose.partMatrix('head').equals(new Matrix4())).toBe(false);
  for (const name of ['antenna_left', 'antenna_right']) {
    expect(Math.max(...pose.partMatrix(name).elements.map((value, at) => Math.abs(value - pose.partMatrix('head').elements[at])))).toBeLessThan(1e-8);
  }
  expect(Math.max(...pose.partMatrix('thorax').elements.map((value, at) => Math.abs(value - new Matrix4().elements[at])))).toBeLessThan(1e-10);
  expect(JSON.stringify(rig)).toBe(saved);
  expect([...model.joints.keys()].some(name => /eye/.test(name))).toBe(false);
});

test('unknown, nonfinite and out-of-range commands fail before changing the body', () => {
  const model = buildFlyKinematics(rig);
  for (const command of [{ eye: .1 }, { head: NaN }, { head: 90 }, { head_abduct: .3 }]) expect(() => model.pose(command)).toThrow('rig_command');
  expect(() => buildFlyKinematics({ ...rig, source_xml_sha256: 'other' })).toThrow('rig_identity');
});
