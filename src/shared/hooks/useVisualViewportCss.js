import { useLayoutEffect } from 'react';

/** One viewport owner for portalled dialogs; keyboard changes never remount forms. */
export default function useVisualViewportCss() {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let frame;
    const measure = () => {
      root.style.setProperty('--app-visual-height', `${viewport?.height || window.innerHeight}px`);
      root.style.setProperty('--app-visual-top', `${viewport?.offsetTop || 0}px`);
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener('resize', schedule);
    viewport?.addEventListener('resize', schedule);
    viewport?.addEventListener('scroll', schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', schedule);
      viewport?.removeEventListener('resize', schedule);
      viewport?.removeEventListener('scroll', schedule);
      root.style.removeProperty('--app-visual-height');
      root.style.removeProperty('--app-visual-top');
    };
  }, []);
}
