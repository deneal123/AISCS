import { useEffect } from 'react';

const ACTION_SELECTOR = '[data-toast-protected-actions]';
const INSET_PROPERTY = '--app-toast-action-inset';
// Clearance includes the toast entrance movement, not a new visual spacing token.
const ACTION_CLEARANCE = 32;

export default function useToastActionProtection() {
  useEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let frame;
    const observed = new Set();
    const measure = () => {
      const top = viewport?.offsetTop || 0;
      const bottom = top + (viewport?.height || window.innerHeight);
      let inset = Math.max(0, window.innerHeight - bottom);
      for (const element of document.querySelectorAll(ACTION_SELECTOR)) {
        const rect = element.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && rect.bottom > top && rect.top < bottom) {
          inset = Math.max(inset, window.innerHeight - rect.top + ACTION_CLEARANCE);
        }
      }
      const value = `${Math.ceil(inset)}px`;
      if (root.style.getPropertyValue(INSET_PROPERTY) !== value) {
        root.style.setProperty(INSET_PROPERTY, value);
      }
    };
    const schedule = () => {
      if (frame != null) return;
      frame = window.requestAnimationFrame(() => {
        frame = undefined;
        measure();
      });
    };
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(schedule);
    const discover = () => {
      const current = new Set(document.querySelectorAll(ACTION_SELECTOR));
      for (const element of observed) {
        if (!current.has(element)) {
          resize?.unobserve(element);
          observed.delete(element);
        }
      }
      for (const element of current) {
        if (!observed.has(element)) {
          observed.add(element);
          resize?.observe(element);
        }
      }
      schedule();
    };
    const mutations = new MutationObserver(discover);
    mutations.observe(document.body, { childList: true, subtree: true });
    resize?.observe(root);
    window.addEventListener('resize', schedule);
    document.addEventListener('scroll', schedule, true);
    viewport?.addEventListener('resize', schedule);
    viewport?.addEventListener('scroll', schedule);
    discover();
    measure();
    return () => {
      if (frame != null) window.cancelAnimationFrame(frame);
      mutations.disconnect();
      resize?.disconnect();
      window.removeEventListener('resize', schedule);
      document.removeEventListener('scroll', schedule, true);
      viewport?.removeEventListener('resize', schedule);
      viewport?.removeEventListener('scroll', schedule);
      root.style.removeProperty(INSET_PROPERTY);
    };
  }, []);
}
