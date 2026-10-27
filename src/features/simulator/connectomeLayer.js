import * as THREE from 'three';

// The event journal alone drives the activity. Input controls never animate it.
export function createConnectomeLayer(data) {
  const group = new THREE.Group(), n = data.node_ids.length;
  const lastSpike = new Float32Array(n).fill(-1000);
  const uniforms = { clock: { value: 0 }, legPose: { value: Array.from({ length: 6 }, () => new THREE.Matrix4()) } };
  const boneFor = index => data.coordinate_kind?.[index] === 0 && data.regions[index] >= 3 && data.regions[index] <= 8 ? data.regions[index] - 3 : -1;
  const bones = Float32Array.from({ length: n }, (_, i) => boneFor(i));
  const poseShader = `uniform mat4 legPose[6]; vec3 posed(vec3 p,float bone){ if(bone<0.0)return p;return (legPose[int(bone)]*vec4(p,1.0)).xyz; }`;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(data.positions_mm, 3));
  geometry.setAttribute('firedAt', new THREE.BufferAttribute(lastSpike, 1).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('bone', new THREE.BufferAttribute(bones, 1));
  const somaMaterial = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, uniforms,
    vertexShader: `${poseShader} attribute float bone; attribute float firedAt; uniform float clock; varying float pulse;
      void main(){ float age=clock-firedAt; pulse=age>=0.0 && age<6.0 ? exp(-age/2.5) : 0.0;
      gl_Position=projectionMatrix*modelViewMatrix*vec4(posed(position,bone),1.0); gl_PointSize=1.3+4.5*pulse; }`,
    fragmentShader: `varying float pulse; void main(){float radius=length(gl_PointCoord-vec2(.5)); if(radius>.5)discard;
      vec3 color=mix(vec3(.28,.50,.68),vec3(.25,1.0,.73),pulse);
      gl_FragColor=vec4(color,(.11+.85*pulse)*(1.0-smoothstep(.18,.5,radius))); }`,
  });
  const points = new THREE.Points(geometry, somaMaterial); points.renderOrder = 5; group.add(points);
  const edgeCount = data.edge_pre.length;
  const edgeBones = new Float32Array(edgeCount * 2), sourceBones = new Float32Array(edgeCount), targetBones = new Float32Array(edgeCount);
  const edgePositions = new Float32Array(edgeCount * 6), targets = new Float32Array(edgeCount * 3);
  const sources = new Float32Array(edgeCount * 3), edgeTimes = new Float32Array(edgeCount).fill(-1000);
  for (let i = 0; i < edgeCount; i += 1) {
    sources.set(data.positions_mm.subarray(data.edge_pre[i] * 3, data.edge_pre[i] * 3 + 3), i * 3);
    targets.set(data.positions_mm.subarray(data.edge_post[i] * 3, data.edge_post[i] * 3 + 3), i * 3);
    edgePositions.set(sources.subarray(i * 3, i * 3 + 3), i * 6);
    edgePositions.set(targets.subarray(i * 3, i * 3 + 3), i * 6 + 3);
    sourceBones[i] = boneFor(data.edge_pre[i]); targetBones[i] = boneFor(data.edge_post[i]);
    edgeBones.set([sourceBones[i], targetBones[i]], i * 2);
  }
  const poseLine = material => {
    material.onBeforeCompile = shader => {
      shader.uniforms.legPose = uniforms.legPose;
      shader.vertexShader = `${poseShader} attribute float bone;\n${shader.vertexShader}`.replace('#include <begin_vertex>', 'vec3 transformed=posed(position,bone);');
    };
  };
  const edges = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(edgePositions, 3)),
    new THREE.LineBasicMaterial({ color: 0x34648a, transparent: true, opacity: .035, depthWrite: false, depthTest: false }));
  edges.geometry.setAttribute('bone', new THREE.BufferAttribute(edgeBones, 1)); poseLine(edges.material);
  edges.renderOrder = 3; group.add(edges);
  const pulseGeometry = new THREE.BufferGeometry();
  pulseGeometry.setAttribute('position', new THREE.BufferAttribute(sources, 3));
  pulseGeometry.setAttribute('target', new THREE.BufferAttribute(targets, 3));
  pulseGeometry.setAttribute('sourceBone', new THREE.BufferAttribute(sourceBones, 1));
  pulseGeometry.setAttribute('targetBone', new THREE.BufferAttribute(targetBones, 1));
  pulseGeometry.setAttribute('firedAt', new THREE.BufferAttribute(edgeTimes, 1).setUsage(THREE.DynamicDrawUsage));
  pulseGeometry.setAttribute('edgePolarity', new THREE.Float32BufferAttribute(data.edge_sign, 1));
  const pulseMaterial = new THREE.ShaderMaterial({ uniforms, transparent: true, depthWrite: false, depthTest: false,
    vertexShader: `${poseShader} attribute float sourceBone; attribute float targetBone; attribute vec3 target; attribute float firedAt; attribute float edgePolarity; uniform float clock; varying float show; varying float polarity;
      void main(){float age=clock-firedAt; show=age>=0.0 && age<2.0 ? 1.0 : 0.0; polarity=edgePolarity;
      gl_Position=projectionMatrix*modelViewMatrix*vec4(mix(posed(position,sourceBone),posed(target,targetBone),clamp(age/2.0,0.0,1.0)),1.0);gl_PointSize=3.5;}`,
    fragmentShader: `varying float show; varying float polarity; void main(){float r=length(gl_PointCoord-vec2(.5)); if(show<.5||r>.5)discard;
      gl_FragColor=vec4(polarity<0.0?vec3(.36,.60,1.0):vec3(.37,1.0,.81),(1.0-smoothstep(.1,.5,r))*.9);}`,
  });
  const pulses = new THREE.Points(pulseGeometry, pulseMaterial); pulses.renderOrder = 6; pulses.frustumCulled = false; group.add(pulses);
  const routes = new THREE.Group();
  Object.entries(data.description.scene.routes_mm).forEach(([region, path]) => {
    const curve = new THREE.CatmullRomCurve3(path.map(point => new THREE.Vector3(...point)));
    const material = new THREE.LineDashedMaterial({ color: 0x54829e, transparent: true, opacity: .38, dashSize: .025, gapSize: .014, depthWrite: false, depthTest: false });
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(64)), material);
    const bone = data.description.scene.regions?.indexOf(region) - 3;
    line.geometry.setAttribute('bone', new THREE.Float32BufferAttribute(Array.from({ length: 65 }, (_, i) => i && bone >= 0 && bone < 6 ? bone : -1), 1));
    poseLine(material);
    line.computeLineDistances(); line.userData.region = region; routes.add(line);
  });
  group.add(routes);
  let cursor = 0, previous = -1, active = 0;
  return { group,
    update(time, xray, visible, legRigs) {
      group.visible = visible;
      ['T1_left', 'T1_right', 'T2_left', 'T2_right', 'T3_left', 'T3_right'].forEach((name, i) => {
        if (legRigs?.has('coxa_' + name)) uniforms.legPose.value[i] = legRigs.get('coxa_' + name).matrix;
      });
      if (time < previous) { cursor = 0; lastSpike.fill(-1000); }
      let changed = false;
      while (cursor < data.spike_times_ms.length && data.spike_times_ms[cursor] <= time) {
        lastSpike[data.spike_neurons[cursor]] = data.spike_times_ms[cursor]; cursor += 1; changed = true;
      }
      if (time < previous) changed = true;
      if (changed) {
        geometry.attributes.firedAt.needsUpdate = true;
        for (let i = 0; i < edgeCount; i += 1) edgeTimes[i] = lastSpike[data.edge_pre[i]];
        pulseGeometry.attributes.firedAt.needsUpdate = true;
      }
      if (time !== previous) {
        active = 0;
        for (let i = 0; i < n; i += 1) if (time - lastSpike[i] >= 0 && time - lastSpike[i] < 6) active += 1;
      }
      previous = time; uniforms.clock.value = time;
      [somaMaterial, pulseMaterial, edges.material, ...routes.children.map(line => line.material)].forEach(material => { material.depthTest = !xray; });
      return { active, delivered: cursor };
    },
    dispose() { group.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); }); },
  };
}
