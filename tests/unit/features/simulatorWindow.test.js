import * as THREE from 'three';
import { createLocalWindow } from '../../../src/features/simulator/sceneWindow';

function viewer(ratio = 1) {
  const container = document.createElement('div');
  const camera = new THREE.PerspectiveCamera(38, 2, .005, 100);
  camera.position.set(0, 0, 2); camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
  const renderer = { domElement: document.createElement('canvas'), getPixelRatio: () => ratio,
    getDrawingBufferSize: vector => vector.set(800 * ratio, 400 * ratio) };
  const window = createLocalWindow(container);
  const update = () => window.update(renderer, camera, new THREE.Vector3(), true);
  return { container, camera, renderer, window, update };
}

test('the local aperture has the same CSS scale at different device pixel ratios', () => {
  const normal = viewer(1), retina = viewer(2);
  normal.update(); retina.update();
  expect(normal.container.firstChild.style.width).toBe(retina.container.firstChild.style.width);
  expect(normal.renderer.domElement.dataset.localWindow).toBe('open');
  normal.window.dispose(); retina.window.dispose();
  expect(normal.container.childElementCount).toBe(0);
  expect(retina.container.childElementCount).toBe(0);
});

test('rotating the view target moves the aperture outline even when its radius is unchanged', () => {
  const view = viewer(); view.update();
  const outline = view.container.firstChild;
  const before = { left: outline.style.left, width: outline.style.width };
  view.camera.lookAt(.5, 0, 0); view.camera.updateMatrixWorld(); view.update();
  expect(outline.style.left).not.toBe(before.left);
  expect(outline.style.width).toBe(before.width);
  view.window.update(view.renderer, view.camera, new THREE.Vector3(), false);
  expect(outline.style.display).toBe('none');
  view.window.dispose();
});
