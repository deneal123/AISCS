import * as THREE from 'three';
import { buildConnectomeRoutes, hasDisplayPosition, LEG_REGIONS, ROUTING_VERSION } from './connectomeRoutes';
import { inspectConnectomeNode } from './connectomeInspection';
import { NATIVE_VIEW_MATRIX } from './connectomeMorphology';
import { createPeripheralLayer } from '../scene/peripheralLayer';

// The event journal alone drives the activity. Input controls never animate it.
export function createConnectomeLayer(data) {
  const group = new THREE.Group(), n = data.node_ids.length;
  const started = performance.now();
  const routing = buildConnectomeRoutes(data);
  group.userData.routing = { version: ROUTING_VERSION, samples: routing.samples, segments: routing.segments,
    visibleNodes: routing.visibleNodes.length, visibleEdges: routing.visibleEdges.length,
    buildMilliseconds: performance.now() - started };
  const clockWidth = Math.min(512, Math.max(1, n)), clockHeight = Math.ceil(n / clockWidth);
  const lastSpike = new Float32Array(clockWidth * clockHeight).fill(-1000);
  const lastSourceCrossing = new Float32Array(n).fill(-1000);
  const spikeAtlas = new THREE.DataTexture(lastSpike, clockWidth, clockHeight, THREE.RedFormat, THREE.FloatType);
  spikeAtlas.minFilter = spikeAtlas.magFilter = THREE.NearestFilter; spikeAtlas.generateMipmaps = false; spikeAtlas.needsUpdate = true;
  const atlas = new THREE.DataTexture(routing.atlas, routing.width, routing.height, THREE.RGBAFormat, THREE.FloatType);
  atlas.minFilter = atlas.magFilter = THREE.NearestFilter; atlas.generateMipmaps = false; atlas.needsUpdate = true;
  const uniforms = { clock: { value: 0 }, synapticDelay: { value: data.description.synaptic_delay_ms }, legPose: { value: Array.from({ length: 6 }, () => new THREE.Matrix4()) },
    selectedNode: { value: -1 }, pointScale: { value: 1 },
    routeAtlas: { value: atlas }, routeAtlasSize: { value: new THREE.Vector2(routing.width, routing.height) },
    spikeAtlas: { value: spikeAtlas }, spikeAtlasSize: { value: new THREE.Vector2(clockWidth, clockHeight) } };
  const poseShader = `uniform mat4 legPose[6]; vec3 posed(vec3 p,float skin){ if(skin<0.0)return p;
    int bone=int(floor(skin*.5));float weight=skin-float(bone)*2.0;
    return mix(p,(legPose[bone]*vec4(p,1.0)).xyz,weight); }`;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(routing.positions, 3));
  geometry.setAttribute('firedAt', new THREE.BufferAttribute(lastSpike.subarray(0, n), 1).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('sourceAt', new THREE.BufferAttribute(lastSourceCrossing, 1).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('bone', new THREE.BufferAttribute(routing.skin, 1));
  const isInput = new Float32Array(n);
  (data.input_indices || []).forEach(i => { isInput[i] = 1; });
  geometry.setAttribute('isInput', new THREE.BufferAttribute(isInput, 1));
  geometry.setAttribute('nodeIndex', new THREE.BufferAttribute(Float32Array.from({ length: n }, (_, i) => i), 1));
  geometry.setIndex(routing.visibleNodes);
  const somaMaterial = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, uniforms,
    vertexShader: `${poseShader} attribute float bone; attribute float firedAt; attribute float sourceAt; attribute float isInput; attribute float nodeIndex;
      uniform float clock; uniform float selectedNode; uniform float pointScale; varying float pulse; varying float inputCell; varying float selected;
      void main(){ float age=clock-firedAt; float sourceAge=clock-sourceAt;
      pulse=max(age>=0.0 && age<6.0 ? exp(-age/2.5) : 0.0,sourceAge>=0.0 && sourceAge<6.0 ? exp(-sourceAge/2.5) : 0.0);
      inputCell=isInput; selected=abs(nodeIndex-selectedNode)<.5 ? 1.0 : 0.0;
      gl_Position=projectionMatrix*modelViewMatrix*vec4(posed(position,bone),1.0); gl_PointSize=selected>0.5 ? 12.0 : pointScale+4.5*pulse; }`,
    fragmentShader: `uniform float pointScale; varying float pulse; varying float inputCell; varying float selected;
      void main(){float radius=length(gl_PointCoord-vec2(.5)); if(radius>.5)discard;
      vec3 response=mix(vec3(.25,1.0,.73),vec3(1.0,.55,.16),inputCell);
      vec3 color=selected>0.5 ? vec3(1.0,.88,.35) : mix(vec3(.39,.61,.82),response,pulse);
      gl_FragColor=vec4(color,(selected>0.5 ? 1.0 : .1+.08*(pointScale-1.3)+.7*pulse)*(1.0-smoothstep(.18,.5,radius))); }`,
  });
  const points = new THREE.Points(geometry, somaMaterial); points.renderOrder = 5; group.add(points);
  const nativeIndices = routing.visibleNodes.filter(index => data.coordinate_kind?.[index] > 0);
  const nativeMatrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX), nativeBounds = new THREE.Box3();
  for (const index of nativeIndices) nativeBounds.expandByPoint(new THREE.Vector3().fromArray(routing.positions, index * 3).applyMatrix4(nativeMatrix));
  const edgeCount = data.edge_pre.length;
  const sources = new Float32Array(edgeCount * 3), edgeTimes = new Float32Array(edgeCount).fill(-1000);
  for (let i = 0; i < edgeCount; i += 1) {
    sources.set(routing.positions.subarray(data.edge_pre[i] * 3, data.edge_pre[i] * 3 + 3), i * 3);
  }
  const pulseGeometry = new THREE.BufferGeometry();
  pulseGeometry.setAttribute('position', new THREE.BufferAttribute(sources, 3));
  pulseGeometry.setAttribute('routeStart', new THREE.BufferAttribute(routing.starts, 1));
  pulseGeometry.setAttribute('routeSteps', new THREE.BufferAttribute(routing.steps, 1));
  pulseGeometry.setAttribute('firedAt', new THREE.BufferAttribute(edgeTimes, 1).setUsage(THREE.DynamicDrawUsage));
  pulseGeometry.setAttribute('edgePolarity', new THREE.Float32BufferAttribute(data.edge_sign, 1));
  pulseGeometry.setIndex(routing.visibleEdges);
  const pulseMaterial = new THREE.ShaderMaterial({ uniforms, transparent: true, depthWrite: false, depthTest: false,
    vertexShader: `${poseShader} uniform sampler2D routeAtlas; uniform vec2 routeAtlasSize;
      attribute float routeStart; attribute float routeSteps; attribute float firedAt; attribute float edgePolarity;
      uniform float clock; uniform float synapticDelay; varying float show; varying float polarity;
      vec4 waypoint(float index){return texture2D(routeAtlas,(vec2(mod(index,routeAtlasSize.x),floor(index/routeAtlasSize.x))+.5)/routeAtlasSize);}
      void main(){float age=clock-firedAt; show=age>=0.0 && age<synapticDelay ? 1.0 : 0.0; polarity=edgePolarity;
      float progress=clamp(age/synapticDelay,0.0,1.0)*routeSteps;float step=floor(progress);
      vec4 a=waypoint(routeStart+step),b=waypoint(routeStart+min(step+1.0,routeSteps));
      gl_Position=projectionMatrix*modelViewMatrix*vec4(mix(posed(a.xyz,a.w),posed(b.xyz,b.w),fract(progress)),1.0);gl_PointSize=3.5;}`,
    fragmentShader: `varying float show; varying float polarity; void main(){float r=length(gl_PointCoord-vec2(.5)); if(show<.5||r>.5)discard;
      gl_FragColor=vec4(polarity<0.0?vec3(.36,.60,1.0):vec3(.37,1.0,.81),(1.0-smoothstep(.1,.5,r))*.9);}`,
  });
  const pulses = new THREE.Points(pulseGeometry, pulseMaterial); pulses.renderOrder = 6; pulses.frustumCulled = false; group.add(pulses);
  const peripheral = createPeripheralLayer(routing.guides, uniforms.legPose, poseShader), routes = peripheral.group;
  group.add(routes);
  let arborMaterial = null;
  if (data.arbors) {
    const arborGeometry = new THREE.BufferGeometry();
    arborGeometry.setAttribute('position', new THREE.BufferAttribute(data.arbors.positions, 3));
    arborGeometry.setAttribute('sourceIndex', new THREE.BufferAttribute(data.arbors.nodeIndices, 1));
    arborMaterial = new THREE.ShaderMaterial({ uniforms, transparent: true, depthWrite: false, depthTest: false,
      vertexShader: `uniform sampler2D spikeAtlas; uniform vec2 spikeAtlasSize; uniform float clock;
        attribute float sourceIndex; varying float pulse;
        void main(){ float fired=texture2D(spikeAtlas,(vec2(mod(sourceIndex,spikeAtlasSize.x),floor(sourceIndex/spikeAtlasSize.x))+.5)/spikeAtlasSize).r;
        float age=clock-fired; pulse=age>=0.0 && age<6.0 ? exp(-age/2.5) : 0.0;
        gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
      fragmentShader: `varying float pulse; void main(){
        gl_FragColor=vec4(mix(vec3(.30,.52,.68),vec3(1.0,.57,.20),sqrt(pulse)),.075+.32*pulse); }`,
    });
    const arbors = new THREE.LineSegments(arborGeometry, arborMaterial); arbors.renderOrder = 4; group.add(arbors);
  }
  const overview = new THREE.Group(); group.add(overview);
  const overviewMaterial = new THREE.ShaderMaterial({ uniforms, transparent: true, depthWrite: false, depthTest: false,
    vertexShader: `uniform sampler2D spikeAtlas; uniform vec2 spikeAtlasSize; uniform float clock;
      attribute float sourceIndex; varying float pulse;
      void main(){ float fired=texture2D(spikeAtlas,(vec2(mod(sourceIndex,spikeAtlasSize.x),floor(sourceIndex/spikeAtlasSize.x))+.5)/spikeAtlasSize).r;
      float age=clock-fired; pulse=age>=0.0 && age<6.0 ? exp(-age/2.5) : 0.0;
      gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: `varying float pulse; void main(){ gl_FragColor=vec4(mix(vec3(.20,.48,.62),vec3(.28,1.0,.72),sqrt(pulse)),.055+.34*pulse); }`,
  });
  let overviewChunks = [];
  let cursor = 0, sourceCursor = 0, previous = -1, active = 0, inputActive = 0, nativeMode = false;
  const nodeIndex = id => {
    let low = 0, high = data.node_ids.length;
    if (!id || !/^[1-9]\d{0,19}$/.test(id)) return -1;
    const target = BigInt(id);
    while (low < high) { const mid = (low + high) >>> 1; if (data.node_ids[mid] < target) low = mid + 1; else high = mid; }
    return low < data.node_ids.length && data.node_ids[low] === target ? low : -1;
  };
  return { group,
    nativeBounds,
    setOverview(chunks) {
      if (overviewChunks === chunks) return;
      if (chunks.length < overviewChunks.length || chunks.some((chunk, i) => i < overviewChunks.length && chunk !== overviewChunks[i])) {
        while (overview.children.length) { const child = overview.children[0]; overview.remove(child); child.geometry.dispose(); }
        overviewChunks = [];
      }
      for (const chunk of chunks.slice(overviewChunks.length)) {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(chunk.positions, 3));
        geometry.setAttribute('sourceIndex', new THREE.BufferAttribute(chunk.nodeIndices, 1));
        const lines = new THREE.LineSegments(geometry, overviewMaterial);
        lines.frustumCulled = false; lines.renderOrder = 3; overview.add(lines);
      }
      overviewChunks = chunks;
    },
    selectNode(id) {
      const index = nodeIndex(id);
      uniforms.selectedNode.value = index;
      return index;
    },
    lastSpikeTime(id) {
      const index = nodeIndex(id);
      return index < 0 || lastSpike[index] < 0 ? null : lastSpike[index];
    },
    nodeWorldPosition(id) {
      const index = nodeIndex(id);
      if (!group.visible || index < 0 || !hasDisplayPosition(data, index) || (nativeMode && !data.coordinate_kind?.[index])) return null;
      const point = new THREE.Vector3().fromArray(routing.positions, index * 3);
      const skin = routing.skin[index];
      if (skin >= 0 && !nativeMode) {
        const bone = Math.floor(skin * .5), weight = skin - bone * 2;
        point.lerp(point.clone().applyMatrix4(uniforms.legPose.value[bone]), weight);
      }
      group.updateWorldMatrix(true, false);
      return point.applyMatrix4(group.matrixWorld);
    },
    coordinateView(native) {
      if (nativeMode === native) return;
      if (native && data.description.scene.embedding !== 'male-cns-flybody-view-only-v2') throw new Error('native_frame_identity');
      nativeMode = native;
      group.matrixAutoUpdate = false;
      if (native) group.matrix.copy(nativeMatrix); else group.matrix.identity();
      group.matrixWorldNeedsUpdate = true;
      // Display connections and peripheral corridors are not traced axons.
      // A native morphology view must not pass them off as source geometry.
      pulses.visible = !native; routes.visible = !native;
      geometry.setIndex(native ? nativeIndices : routing.visibleNodes);
    },
    inspect(raycaster, timeMs) {
      const candidates = this.inspectCandidates(raycaster);
      return candidates.length ? this.inspectIndex(candidates[0], timeMs) : null;
    },
    inspectCandidates(raycaster) {
      if (!group.visible) return [];
      // Shader-only limb poses cannot be raycast as if they were static anatomy.
      // Inspect source-positioned CNS landmarks, never schematic peripheral paths.
      const hits = raycaster.intersectObject(points, false)
        .filter(hit => routing.skin[hit.index] < 0);
      hits.sort((a, b) => a.distanceToRay - b.distanceToRay || a.distance - b.distance);
      return hits.slice(0, 64).map(hit => hit.index);
    },
    inspectIndex(index, timeMs) {
      return inspectConnectomeNode(data, index, timeMs);
    },
    update(time, xray, visible, legRigs, peripheralView = {}) {
      group.visible = visible;
      const distance = peripheralView.cameraDistance;
      uniforms.pointScale.value = Number.isFinite(distance) && distance > 0
        ? Math.min(5, 1.3 + .45 / distance) : 1.3;
      routes.visible = !nativeMode && peripheralView.visible !== false;
      LEG_REGIONS.forEach((name, i) => {
        const joint = 'coxa_' + name.replace('front', 'T1').replace('middle', 'T2').replace('hind', 'T3');
        uniforms.legPose.value[i] = legRigs?.get(joint)?.matrix || new THREE.Matrix4();
      });
      if (time < previous) { cursor = 0; sourceCursor = 0; lastSpike.fill(-1000); lastSourceCrossing.fill(-1000); }
      let changed = false;
      while (cursor < data.spike_times_ms.length && data.spike_times_ms[cursor] <= time) {
        lastSpike[data.spike_neurons[cursor]] = data.spike_times_ms[cursor]; cursor += 1; changed = true;
      }
      let sourceChanged = time < previous;
      while (sourceCursor < (data.physical_source_times_ms?.length || 0) && data.physical_source_times_ms[sourceCursor] <= time) {
        lastSourceCrossing[data.physical_source_indices[sourceCursor]] = data.physical_source_times_ms[sourceCursor];
        sourceCursor += 1; sourceChanged = true;
      }
      if (sourceChanged) geometry.attributes.sourceAt.needsUpdate = true;
      if (time < previous) changed = true;
      if (changed) {
        geometry.attributes.firedAt.needsUpdate = true;
        spikeAtlas.needsUpdate = true;
        for (let i = 0; i < edgeCount; i += 1) edgeTimes[i] = lastSpike[data.edge_pre[i]];
        pulseGeometry.attributes.firedAt.needsUpdate = true;
      }
      if (time !== previous) {
        active = 0; inputActive = 0;
        for (let i = 0; i < n; i += 1) if (time - lastSpike[i] >= 0 && time - lastSpike[i] < 6) {
          active += 1; if (isInput[i]) inputActive += 1;
        }
      }
      previous = time; uniforms.clock.value = time;
      [somaMaterial, pulseMaterial, arborMaterial, overviewMaterial, ...routes.children.map(line => line.material)].filter(Boolean).forEach(material => { material.depthTest = !xray; });
      const peripheralActivity = peripheral.update(peripheralView.readout, time, xray, peripheralView.width, peripheralView.height);
      return { active, inputActive, delivered: cursor, sourceDelivered: sourceCursor,
        peripheralActivity, pointScale: uniforms.pointScale.value,
        peripheralVisible: group.visible && routes.visible, peripheralPaths: Object.keys(routing.guides).length };
    },
    dispose() { group.traverse(object => { object.geometry?.dispose(); if (object.material !== overviewMaterial) object.material?.dispose(); }); overviewMaterial.dispose(); atlas.dispose(); spikeAtlas.dispose(); },
  };
}
