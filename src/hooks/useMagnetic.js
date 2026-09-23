import { useEffect, useRef } from "react";
import { isCoarsePointer, prefersReducedMotion } from "../utils/motion";

/**
 * Магнитная тяга: элемент чуть смещается к курсору. Gated — no-op под
 * reduced-motion / тач. CSS-`transition` элемента сглаживает возврат.
 * Порт docs/design_transfer/07 (useMagnetic.ts).
 *
 * Геометрию читаем ОДИН раз при входе курсора, а transform пишем в rAF: раньше
 * каждый pointermove вызывал getBoundingClientRect() и тут же писал стиль — это
 * принудительный пересчёт лэйаута 60-120 раз в секунду, поверх WebGL-фона и
 * стеклянных blur-слоёв. Магнитные кнопки стоят на всех главных CTA и в шапке.
 */
export function useMagnetic(strength = 6) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (prefersReducedMotion() || isCoarsePointer()) return undefined;

    let rect = null;
    let raf = 0;
    let pointer = null;

    const apply = () => {
      raf = 0;
      if (!pointer || !rect) return;
      const dx = ((pointer.x - rect.left) / rect.width - 0.5) * 2 * strength;
      const dy = ((pointer.y - rect.top) / rect.height - 0.5) * 2 * strength;
      el.style.transform = `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px)`;
    };

    const handleEnter = () => {
      rect = el.getBoundingClientRect();
    };
    const handleMove = (e) => {
      if (!rect) rect = el.getBoundingClientRect();
      pointer = { x: e.clientX, y: e.clientY };
      if (!raf) raf = requestAnimationFrame(apply);
    };
    const handleLeave = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      pointer = null;
      rect = null;
      el.style.transform = "";
    };

    el.addEventListener("pointerenter", handleEnter);
    el.addEventListener("pointermove", handleMove, { passive: true });
    el.addEventListener("pointerleave", handleLeave);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      el.removeEventListener("pointerenter", handleEnter);
      el.removeEventListener("pointermove", handleMove);
      el.removeEventListener("pointerleave", handleLeave);
      el.style.transform = "";
    };
  }, [strength]);

  return ref;
}
