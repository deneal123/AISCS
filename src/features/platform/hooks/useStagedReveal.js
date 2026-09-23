import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "@utils/motion";

/**
 * Поэтапный показ диалога витрины: возвращает `shown` (0..total), который растёт
 * по одному шагу каждые `stepMs`, когда `active=true` (обычно из useInView —
 * окно въехало во вьюпорт). Под prefers-reduced-motion — сразу `total` (без
 * стейджа, весь диалог виден). Пересобирается при смене ключа (ремоунт по табу).
 */
export function useStagedReveal(total, { active = true, stepMs = 300, startDelay = 120 } = {}) {
  const reduced = prefersReducedMotion();
  const [shown, setShown] = useState(reduced ? total : 0);
  const timers = useRef([]);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];

    if (reduced) {
      setShown(total);
      return undefined;
    }
    if (!active) {
      setShown(0);
      return undefined;
    }

    setShown(0);
    for (let i = 1; i <= total; i += 1) {
      timers.current.push(
        setTimeout(() => setShown(i), startDelay + (i - 1) * stepMs),
      );
    }
    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [total, active, stepMs, startDelay, reduced]);

  return shown;
}

export default useStagedReveal;
