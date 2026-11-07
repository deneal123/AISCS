import * as THREE from 'three';
import { peripheralCountsAtTime } from './peripheralReadout';

// Pixel-width ribbons keep the body corridors legible at both viewport sizes.
// All three traces follow the same path/pose. Activity lights the whole bundle:
// drawing a travelling wave here would invent unmodelled peripheral conduction.
export function createPeripheralLayer(guides, legPose, poseShader) {
  const group = new THREE.Group(), entries = [];
  const resolution = { value: new THREE.Vector2(1, 1) };
  for (const [region, path] of Object.entries(guides)) {
    const geometry = new THREE.BufferGeometry(), positions = [], others = [], bones = [], otherBones = [], sides = [], directions = [], distances = [];
    let length = 0;
    for (let i = 0; i < path.length - 1; i += 1) {
      const a = path[i], b = path[i + 1], next = length + Math.hypot(...a.p.map((v, axis) => v - b.p[axis]));
      for (const [end, side] of [[0, -1], [0, 1], [1, 1], [0, -1], [1, 1], [1, -1]]) {
        const point = end ? b : a, other = end ? a : b;
        positions.push(...point.p); others.push(...other.p); bones.push(point.skin); otherBones.push(other.skin);
        sides.push(end ? -side : side); directions.push(end ? -1 : 1); distances.push(end ? next : length);
      }
      length = next;
    }
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('other', new THREE.Float32BufferAttribute(others, 3));
    geometry.setAttribute('bone', new THREE.Float32BufferAttribute(bones, 1));
    geometry.setAttribute('otherBone', new THREE.Float32BufferAttribute(otherBones, 1));
    geometry.setAttribute('side', new THREE.Float32BufferAttribute(sides, 1));
    geometry.setAttribute('forward', new THREE.Float32BufferAttribute(directions, 1));
    geometry.setAttribute('pathDistance', new THREE.Float32BufferAttribute(distances, 1));
    const materials = [];
    for (const [channel, color, offset] of [[-1, 0x8baac0, 0], [0, 0xffad62, -1.6], [1, 0x51edbb, 1.6]]) {
      const material = new THREE.ShaderMaterial({
        transparent: true, depthWrite: false, depthTest: false, side: THREE.DoubleSide,
        uniforms: { legPose, resolution, level: { value: channel < 0 ? .7 : 0 }, color: { value: new THREE.Color(color) },
          offset: { value: offset }, width: { value: channel < 0 ? 1.4 : 2.0 }, dashed: { value: channel < 0 ? 1 : 0 } },
        vertexShader: `${poseShader}
          uniform vec2 resolution; uniform float width; uniform float offset;
          attribute vec3 other; attribute float bone; attribute float otherBone;
          attribute float side; attribute float forward; attribute float pathDistance; varying float distanceAlong;
          void main(){
            vec4 a=projectionMatrix*modelViewMatrix*vec4(posed(position,bone),1.0);
            vec4 b=projectionMatrix*modelViewMatrix*vec4(posed(other,otherBone),1.0);
            vec2 delta=(b.xy/b.w-a.xy/a.w)*resolution;
            vec2 normal=vec2(-delta.y,delta.x)/max(length(delta),.0001);
            a.xy+=normal*(side*width+forward*offset*2.0)*a.w/resolution;
            gl_Position=a; distanceAlong=pathDistance;
          }`,
        fragmentShader: `uniform vec3 color; uniform float level; uniform float dashed;
          varying float distanceAlong;
          void main(){if(level<.001)discard;
            if(dashed>.5 && mod(distanceAlong,.04)>.027)discard;
            gl_FragColor=vec4(color,level);
            #include <colorspace_fragment>
          }`,
      });
      const mesh = new THREE.Mesh(geometry, material); mesh.frustumCulled = false; mesh.renderOrder = channel < 0 ? 4 : 7;
      group.add(mesh); materials.push(material);
    }
    entries.push({ region, materials });
  }
  return { group,
    update(readout, timeMs, xray, width, height) {
      resolution.value.set(Math.max(1, width || 1), Math.max(1, height || 1));
      const active = {};
      for (const { region, materials } of entries) {
        const counts = peripheralCountsAtTime(readout, region, timeMs);
        active[region] = counts;
        materials.forEach(material => { material.depthTest = !xray; });
        for (let role = 0; role < 2; role += 1) materials[role + 1].uniforms.level.value = 1 - Math.exp(-counts[role] / 2);
      }
      return active;
    },
  };
}
