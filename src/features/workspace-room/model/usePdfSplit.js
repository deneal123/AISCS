import { useCallback, useEffect, useRef, useState } from 'react';

/** Non-sensitive geometry only. Pointer capture and keyboard share one bound. */
export function useWorkbenchSplit(axis, initial, { namespace = 'pdf', label, min = 30, max = 70 } = {}) {
  const key = `gpthub.${namespace}.split.${axis}`;
  const clamp = useCallback((value) => Math.max(min, Math.min(max, value)), [min, max]);
  const [value, setValue] = useState(() => {
    try {
      const stored = Number(localStorage.getItem(key));
      return stored >= min && stored <= max ? stored : initial;
    } catch { return initial; }
  });
  const drag = useRef(null);
  const frame = useRef(0);
  const pending = useRef(value);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  const commit = useCallback((next) => {
    const bounded = clamp(next);
    pending.current = bounded;
    setValue(bounded);
    try { localStorage.setItem(key, String(bounded)); } catch { /* Storage is optional. */ }
  }, [clamp, key]);
  return {
    value,
    props: {
      role: 'separator', tabIndex: 0,
      'aria-orientation': axis === 'x' ? 'vertical' : 'horizontal',
      'aria-label': label || (axis === 'x' ? 'Ширина редактора и превью' : 'Высота редактора и ассистента'),
      'aria-valuemin': min, 'aria-valuemax': max, 'aria-valuenow': Math.round(value),
      onKeyDown(event) {
        const negative = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
        const positive = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
        if (![negative, positive, 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        commit(event.key === 'Home' ? min : event.key === 'End' ? max
          : value + (event.key === negative ? -2 : 2));
      },
      onPointerDown(event) {
        drag.current = { rect: event.currentTarget.parentElement.getBoundingClientRect(), start: value };
        pending.current = value;
        event.currentTarget.setPointerCapture(event.pointerId);
      },
      onPointerMove(event) {
        if (!drag.current) return;
        const rect = drag.current.rect;
        const next = axis === 'x' ? (event.clientX - rect.left) / rect.width
          : (event.clientY - rect.top) / rect.height;
        cancelAnimationFrame(frame.current);
        pending.current = clamp(next * 100);
        frame.current = requestAnimationFrame(() => setValue(pending.current));
      },
      onPointerUp() {
        if (!drag.current) return;
        cancelAnimationFrame(frame.current); drag.current = null; commit(pending.current);
      },
      onPointerCancel() {
        cancelAnimationFrame(frame.current);
        if (drag.current) setValue(drag.current.start);
        drag.current = null;
      },
      onLostPointerCapture() {
        cancelAnimationFrame(frame.current);
        if (drag.current) setValue(drag.current.start);
        drag.current = null;
      },
    },
  };
}

export function usePdfSplit(axis, initial) {
  return useWorkbenchSplit(axis, initial);
}
