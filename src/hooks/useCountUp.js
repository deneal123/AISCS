import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../utils/motion";

/**
 * Анимированный счётчик от 0 к target, стартует когда active=true (обычно из
 * useInView). Под reduced-motion — сразу финальное значение (без анимации).
 * Лёгкая геймификация метрик (docs/design_transfer/06 Stat + counter-tick).
 */
export function useCountUp(target, { active = true, duration = 1100 } = {}) {
  const [value, setValue] = useState(0);
  const rafRef = useRef(0);
  const startRef = useRef(0);

  useEffect(() => {
    const end = Number(target) || 0;
    if (!active) return undefined;
    if (prefersReducedMotion()) {
      setValue(end);
      return undefined;
    }

    // Нечего анимировать — не гоняем 60 кадров ради «0» (метрики лендинга
    // бывают нулевыми, и счётчик делал ~66 рендеров, каждый раз рисуя одно и то же).
    if (end === 0) {
      setValue(0);
      return undefined;
    }

    const tick = (now) => {
      if (!startRef.current) startRef.current = now;
      const elapsed = now - startRef.current;
      const t = Math.min(1, elapsed / duration);
      // easeOutCubic — совпадает с фирменным --ease-out по ощущению.
      const eased = 1 - Math.pow(1 - t, 3);
      // Округляем ЗДЕСЬ: потребитель всё равно показывает целое, а float на
      // каждый кадр давал ~85% рендеров с тем же самым числом на экране.
      setValue(Math.round(end * eased));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setValue(end);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafRef.current);
      startRef.current = 0;
    };
  }, [target, active, duration]);

  return value;
}
