/** Deliver layout-changing resize work outside ResizeObserver's delivery loop. */
export function observeResizeFrame(element, callback, options) {
  if (!element || typeof ResizeObserver === 'undefined') return () => {};
  let frame = null;
  let latest;
  let disposed = false;
  const observer = new ResizeObserver(entries => {
    if (disposed) return;
    latest = entries;
    if (frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      const entries = latest;
      latest = undefined;
      if (!disposed) callback(entries);
    });
  });
  observer.observe(element, options);
  return () => {
    disposed = true;
    observer.disconnect();
    if (frame !== null) cancelAnimationFrame(frame);
    latest = undefined;
  };
}
