import * as THREE from 'three';
import { NATIVE_VIEW_MATRIX } from './connectome/connectomeMorphology';

// The colour encodes the saved difference against a same-seed control, not a spike.
export function createStateContrastLayer(graph, state) {
  const visible = [];
  state.indices.forEach((index, column) => { if (graph.coordinate_kind[index] > 0) visible.push([index, column]); });
  const positions = new Float32Array(visible.length * 3), changes = new Float32Array(visible.length);
  const sparseToVisible = state.sparse ? new Int32Array(graph.node_ids.length).fill(-1) : null;
  visible.forEach(([index], i) => positions.set(graph.positions_mm.subarray(index * 3, index * 3 + 3), i * 3));
  if (sparseToVisible) visible.forEach(([index], i) => { sparseToVisible[index] = i; });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('change', new THREE.BufferAttribute(changes, 1).setUsage(THREE.DynamicDrawUsage));
  const material = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false,
    uniforms: { scale: { value: state.maximum || 1 } },
    vertexShader: `attribute float change; uniform float scale; varying float intensity; varying float polarity;
      void main(){ intensity=clamp(abs(change)/scale,0.0,1.0); polarity=sign(change);
      gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);
      gl_PointSize=intensity>0.001 ? 2.4+5.1*sqrt(intensity) : 0.0; }`,
    fragmentShader: `varying float intensity; varying float polarity;
      void main(){ float r=length(gl_PointCoord-vec2(0.5)); if(r>0.5 || intensity<=0.001) discard;
      vec3 color=polarity>0.0 ? vec3(1.0,0.57,0.12) : vec3(0.16,0.78,1.0);
      gl_FragColor=vec4(color,(0.30+0.65*sqrt(intensity))*(1.0-smoothstep(0.18,0.5,r))); }`,
  });
  const points = new THREE.Points(geometry, material);
  const nativeMatrix = new THREE.Matrix4().set(...NATIVE_VIEW_MATRIX);
  points.matrixAutoUpdate = false;
  points.matrix.copy(nativeMatrix);
  points.matrixWorldNeedsUpdate = true;
  // Keep discrete model events visible above the denser state background.
  points.renderOrder = 4;
  let previous = -1, active = 0, previousChanged = [];
  return {
    points, visibleCells: visible.length,
    coordinateView(native) {
      if (native) points.matrix.copy(nativeMatrix); else points.matrix.identity();
      points.matrixWorldNeedsUpdate = true;
    },
    update(timeMs) {
      let sample = Math.max(0, Math.min(state.samples - 1, Math.floor(timeMs)));
      if (state.sampleTimes) {
        let low = 0, high = state.sampleTimes.length;
        while (low < high) { const mid = (low + high) >>> 1; if (state.sampleTimes[mid] <= timeMs) low = mid + 1; else high = mid; }
        sample = Math.max(0, low - 1);
      }
      const sampleTime = state.sampleTimes?.[sample] ?? sample;
      if (sample === previous) return { sample: sampleTime, active };
      active = 0;
      if (state.sparse) {
        previousChanged.forEach(index => { changes[index] = 0; }); previousChanged = [];
        for (let i = state.offsets[sample]; i < state.offsets[sample + 1]; i += 1) {
          const visibleIndex = sparseToVisible[state.sparseIndices[i]];
          if (visibleIndex >= 0) { changes[visibleIndex] = state.values[i]; previousChanged.push(visibleIndex);
            if (Math.abs(state.values[i]) > state.maximum * .001) active += 1; }
        }
      } else {
        visible.forEach(([, column], i) => { changes[i] = state.values[sample * state.cells + column];
          if (Math.abs(changes[i]) > state.maximum * .001) active += 1; });
      }
      geometry.attributes.change.needsUpdate = true; previous = sample;
      return { sample: sampleTime, active };
    },
    bounds(timeMs) {
      this.update(timeMs);
      const bounds = new THREE.Box3(), point = new THREE.Vector3();
      for (let i = 0; i < changes.length; i += 1) {
        if (Math.abs(changes[i]) <= state.maximum * .001) continue;
        bounds.expandByPoint(point.fromArray(positions, i * 3).applyMatrix4(points.matrix));
      }
      return bounds;
    },
    dispose() { geometry.dispose(); material.dispose(); },
  };
}
