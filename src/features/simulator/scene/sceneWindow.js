import * as THREE from 'three';

// A view-only aperture. Source meshes, raycasting and model coordinates remain
// unchanged; only body fragments inside the projected local window are hidden.
export function createLocalWindow(container) {
  const uniforms = {
    localWindowEnabled: { value: 0 },
    localWindowCenter: { value: new THREE.Vector2() },
    localWindowRadius: { value: 0 },
  };
  const border = document.createElement('div');
  border.dataset.localWindowOutline = 'true';
  border.setAttribute('aria-hidden', 'true');
  Object.assign(border.style, {
    position: 'absolute', border: '1px solid rgba(145,175,255,.7)',
    borderRadius: '50%', pointerEvents: 'none', display: 'none',
  });
  container.appendChild(border);
  const buffer = new THREE.Vector2(), projected = new THREE.Vector3();
  let borderKey = '';
  return {
    attach(material, apertureOnly = false) {
      material.onBeforeCompile = shader => {
        Object.assign(shader.uniforms, uniforms);
        shader.fragmentShader = `uniform float localWindowEnabled;
uniform vec2 localWindowCenter;
uniform float localWindowRadius;
${shader.fragmentShader}`.replace('#include <clipping_planes_fragment>',
          `#include <clipping_planes_fragment>
${apertureOnly
    ? 'if (localWindowEnabled < 0.5 || distance(gl_FragCoord.xy, localWindowCenter) >= localWindowRadius) discard;'
    : 'if (localWindowEnabled > 0.5 && distance(gl_FragCoord.xy, localWindowCenter) < localWindowRadius) discard;'}`);
      };
      material.customProgramCacheKey = () => `local-aperture-v1-${apertureOnly ? 'ghost' : 'body'}`;
    },
    update(renderer, camera, center, enabled) {
      renderer.getDrawingBufferSize(buffer);
      projected.copy(center).project(camera);
      const distance = camera.position.distanceTo(center);
      const radius = .28 * buffer.y / (2 * distance * Math.tan(camera.fov * Math.PI / 360));
      const visible = enabled && projected.z >= -1 && projected.z <= 1 && Number.isFinite(radius);
      uniforms.localWindowEnabled.value = visible ? 1 : 0;
      uniforms.localWindowCenter.value.set((projected.x + 1) * buffer.x / 2, (projected.y + 1) * buffer.y / 2);
      uniforms.localWindowRadius.value = radius;
      const nextBorder = `${visible}:${uniforms.localWindowCenter.value.x}:${uniforms.localWindowCenter.value.y}:${radius}:${buffer.x}:${buffer.y}:${renderer.getPixelRatio()}`;
      const borderChanged = nextBorder !== borderKey;
      if (borderChanged) {
        borderKey = nextBorder;
        border.style.display = visible ? 'block' : 'none';
        renderer.domElement.dataset.localWindow = visible ? 'open' : 'closed';
        renderer.domElement.dataset.localWindowRadiusPx = (radius / renderer.getPixelRatio()).toFixed(2);
      }
      if (visible && borderChanged) {
        const ratio = renderer.getPixelRatio();
        border.style.left = `${(uniforms.localWindowCenter.value.x - radius) / ratio}px`;
        border.style.top = `${(buffer.y - uniforms.localWindowCenter.value.y - radius) / ratio}px`;
        border.style.width = border.style.height = `${2 * radius / ratio}px`;
      }
    },
    dispose() { border.remove(); },
  };
}
