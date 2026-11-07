import * as THREE from 'three';
import { maleCnsViewPosition, NATIVE_VIEW_MATRIX } from '../connectome/connectomeMorphology';

const contacts = [
  ['source_um', 'STIM+', 0xff9859],
  ['return_um', 'STIM−', 0xf1c15c],
  ['electrode_um', 'E1', 0x5d8fff],
  ['reference_um', 'REF', 0xc5d4ff],
];

// Visual landmarks only: the body embedding is not an anatomical registration.
export function createFieldContactLayer(simulation, normals = {}) {
  const points = contacts.map(([key, label, color]) => {
    const position = simulation?.[key];
    if (!Array.isArray(position) || position.length !== 3 || !position.every(Number.isFinite)) {
      throw new Error('invalid_field_contact');
    }
    return { key, label, color, position: maleCnsViewPosition(position), normal: normals[key] };
  });
  const group = new THREE.Group();
  // Probe dimensions are visual only; contact coordinates remain at the tip.
  const tipGeometry = new THREE.ConeGeometry(.004, .025, 12);
  const shaftGeometry = new THREE.CylinderGeometry(.006, .003, .30, 12);
  const bandGeometry = new THREE.CylinderGeometry(.009, .009, .024, 12);
  const hitGeometry = new THREE.CylinderGeometry(.035, .035, .36, 12);
  const hitMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false });
  const outlineGeometry = new THREE.CylinderGeometry(.010, .007, .32, 12);
  const hoverOutline = new THREE.MeshBasicMaterial({ color: 0x9ed8ff, side: THREE.BackSide, depthTest: false });
  const selectedOutline = new THREE.MeshBasicMaterial({ color: 0xffc071, side: THREE.BackSide, depthTest: false });
  const shaftMaterial = new THREE.MeshStandardMaterial({ color: 0xc3ccd8, metalness: .85, roughness: .24 });
  const materials = [shaftMaterial];
  const textures = [];
  points.forEach(({ key, label, color, position, normal }, index) => {
    const material = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: .25 });
    materials.push(material);
    const marker = new THREE.Group(); marker.position.fromArray(position); marker.name = label; marker.userData.contactKey = key;
    if (Array.isArray(normal) && normal.length === 3 && normal.every(Number.isFinite)
        && Math.hypot(...normal) > 1e-9) marker.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...normal).normalize());
    const tip = new THREE.Mesh(tipGeometry, shaftMaterial); tip.name = 'contact-tip';
    tip.rotation.x = -Math.PI / 2; tip.position.z = .0125; marker.add(tip);
    const shaft = new THREE.Mesh(shaftGeometry, shaftMaterial); shaft.name = 'probe-shaft';
    shaft.rotation.x = Math.PI / 2; shaft.position.z = .175; marker.add(shaft);
    const band = new THREE.Mesh(bandGeometry, material); band.rotation.x = Math.PI / 2; band.position.z = .34; marker.add(band);
    const hitTarget = new THREE.Mesh(hitGeometry, hitMaterial); hitTarget.name = 'probe-hit-target';
    hitTarget.rotation.x = Math.PI / 2; hitTarget.position.z = .18; marker.add(hitTarget);
    for (const [name, outlineMaterial] of [['probe-hover-outline', hoverOutline], ['probe-selected-outline', selectedOutline]]) {
      const outline = new THREE.Mesh(outlineGeometry, outlineMaterial); outline.name = name;
      outline.rotation.x = Math.PI / 2; outline.position.z = .175; outline.visible = false; outline.renderOrder = 11; marker.add(outline);
    }
    if (typeof navigator !== 'undefined' && !/jsdom/i.test(navigator.userAgent)) {
      const canvas = document.createElement('canvas'); canvas.width = 160; canvas.height = 64;
      const context = canvas.getContext('2d');
      if (context) {
        context.fillStyle = 'rgba(8,13,25,.88)'; context.fillRect(0, 0, 160, 64);
        context.font = '600 32px sans-serif'; context.fillStyle = '#f4f7ff'; context.fillText(label, 9, 44);
        const texture = new THREE.CanvasTexture(canvas); textures.push(texture);
        const labelMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
        materials.push(labelMaterial);
        const sprite = new THREE.Sprite(labelMaterial); sprite.name = 'contact-label';
        sprite.scale.set(.30, .12, 1); sprite.position.set(index % 2 ? -.09 : .09, 0, .40 + .05 * (index % 2)); sprite.renderOrder = 12; marker.add(sprite);
      }
    }
    group.add(marker);
  });
  group.matrixAutoUpdate = false;
  const nativeMatrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX);
  return {
    group,
    coordinateView(native) {
      if (native) group.matrix.copy(nativeMatrix); else group.matrix.identity();
      group.matrixWorldNeedsUpdate = true;
    },
    setHighlight(hovered, selected) {
      group.children.forEach(marker => {
        marker.getObjectByName('probe-hover-outline').visible = marker.userData.contactKey === hovered && marker.userData.contactKey !== selected;
        marker.getObjectByName('probe-selected-outline').visible = marker.userData.contactKey === selected;
      });
    },
    dispose() { tipGeometry.dispose(); shaftGeometry.dispose(); bandGeometry.dispose(); hitGeometry.dispose(); hitMaterial.dispose(); outlineGeometry.dispose(); hoverOutline.dispose(); selectedOutline.dispose(); textures.forEach(texture => texture.dispose()); materials.forEach(material => material.dispose()); },
  };
}
