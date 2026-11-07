import { preventSimulatorPageZoom } from '../../../src/features/simulator/pageZoomGuard';

test('blocks trackpad pinch outside the scene while preserving normal scrolling and scene zoom', () => {
  const outside = document.createElement('div');
  const canvas = document.createElement('canvas'); canvas.dataset.simulatorScene = 'true';
  const event = (target, ctrlKey) => ({ target, ctrlKey, preventDefault: jest.fn() });
  const pinchOutside = event(outside, true); preventSimulatorPageZoom(pinchOutside);
  expect(pinchOutside.preventDefault).toHaveBeenCalledTimes(1);
  const normalScroll = event(outside, false); preventSimulatorPageZoom(normalScroll);
  expect(normalScroll.preventDefault).not.toHaveBeenCalled();
  const pinchScene = event(canvas, true); preventSimulatorPageZoom(pinchScene);
  expect(pinchScene.preventDefault).not.toHaveBeenCalled();
});
