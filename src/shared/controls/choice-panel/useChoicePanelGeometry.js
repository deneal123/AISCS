import { useLayoutEffect, useState } from 'react';
import { observeResizeFrame } from '../../utils/observeResizeFrame';

/** Геометрия первого открытия готова до paint; дальнейшие resize объединяются в RAF. */
export default function useChoicePanelGeometry(open, triggerRef) {
  const [geometry, setGeometry] = useState(() => ({
    viewportHeight: window.visualViewport?.height || window.innerHeight,
    viewportBottomInset: 0,
    gutter: 10,
    panelHeight: window.innerHeight - 24,
  }));

  useLayoutEffect(() => {
    if (!open) return undefined;
    const viewport = window.visualViewport;
    const surface = triggerRef.current?.closest('[data-composer-container]')
      ?.querySelector('[data-composer-input-surface]');
    const resize = () => {
      const height = viewport?.height || window.innerHeight;
      const top = surface?.getBoundingClientRect().top;
      const next = {
        viewportHeight: height,
        viewportBottomInset: Math.max(0, window.innerHeight - height - (viewport?.offsetTop || 0)),
        gutter: top != null ? Math.max(10, triggerRef.current.getBoundingClientRect().top - top + 10) : 10,
        panelHeight: top != null ? Math.max(120, Math.min(height - 24, top - 24)) : height - 24,
      };
      setGeometry(previous => Object.keys(next).every(key => previous[key] === next[key]) ? previous : next);
    };
    resize();
    const stopObserving = observeResizeFrame(surface, resize);
    viewport?.addEventListener('resize', resize);
    viewport?.addEventListener('scroll', resize);
    window.addEventListener('resize', resize);
    return () => {
      viewport?.removeEventListener('resize', resize);
      viewport?.removeEventListener('scroll', resize);
      window.removeEventListener('resize', resize);
      stopObserving();
    };
  }, [open, triggerRef]);

  return geometry;
}
