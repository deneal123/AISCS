import * as THREE from 'three';

// Source body links and hinge anchors, not bones or recovered neural anatomy.
// Existing conditional leg poses are applied to both their mesh and these anchors.
export function createFlyJointLayer(rig) {
  const group = new THREE.Group(), neutral = rig.neutral;
  const ancestry = rig.bodies.map((body, index) => {
    let parent = index;
    while (parent > 0) {
      const name = rig.bodies[parent].name;
      if (name.startsWith('coxa_')) return name;
      parent = rig.bodies[parent].parent;
    }
    return null;
  });
  const anchors = [...rig.joints.values()].map(joint => ({
    point: neutral.anchors.get(joint.name), leg: ancestry[rig.names.get(joint.body)],
  }));
  const links = [];
  rig.bodies.forEach((body, index) => {
    if (body.parent === null || body.parent === 0) return;
    links.push({ point: new THREE.Vector3().setFromMatrixPosition(neutral.world[body.parent]), leg: ancestry[body.parent] },
      { point: new THREE.Vector3().setFromMatrixPosition(neutral.world[index]), leg: ancestry[index] });
  });
  const pointGeometry = new THREE.BufferGeometry(), lineGeometry = new THREE.BufferGeometry();
  pointGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(anchors.length * 3), 3));
  lineGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(links.length * 3), 3));
  const pointMaterial = new THREE.PointsMaterial({ color: 0xe5eaf3, size: 4.5, sizeAttenuation: false,
    transparent: true, opacity: .9, depthTest: false, depthWrite: false });
  const lineMaterial = new THREE.LineBasicMaterial({ color: 0xd2d9e7, transparent: true, opacity: .55, depthTest: false, depthWrite: false });
  const points = new THREE.Points(pointGeometry, pointMaterial), lines = new THREE.LineSegments(lineGeometry, lineMaterial);
  points.renderOrder = 9; lines.renderOrder = 8; points.frustumCulled = lines.frustumCulled = false;
  group.add(lines, points);
  const point = new THREE.Vector3();
  return { group,
    update(legRigs, xray) {
      for (const [items, geometry] of [[anchors, pointGeometry], [links, lineGeometry]]) {
        items.forEach((anchor, index) => {
          point.copy(anchor.point);
          if (anchor.leg && legRigs?.has(anchor.leg)) point.applyMatrix4(legRigs.get(anchor.leg).matrix);
          geometry.attributes.position.setXYZ(index, point.x, point.y, point.z);
        });
        geometry.attributes.position.needsUpdate = true;
      }
      pointMaterial.depthTest = lineMaterial.depthTest = !xray;
    },
    dispose() { pointGeometry.dispose(); lineGeometry.dispose(); pointMaterial.dispose(); lineMaterial.dispose(); },
  };
}
