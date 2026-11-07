// Trackpad pinch is exposed as Ctrl+wheel in Chromium. Outside the scene it
// must not resize the application; normal scrolling and keyboard zoom remain.
export function preventSimulatorPageZoom(event) {
  if (!event.ctrlKey) return;
  const target = event.target;
  if (!(target instanceof Element) || !target.closest('canvas[data-simulator-scene]')) event.preventDefault();
}
