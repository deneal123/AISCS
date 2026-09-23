import { useEffect, useRef, useState } from "react";
import { isFigmaCaptureMode } from "../utils/motion";

/**
 * One-shot IntersectionObserver: возвращает [ref, inView], где inView становится
 * true один раз, когда элемент попадает во вьюпорт. В capture-режиме или без
 * IntersectionObserver — сразу true (контент всегда виден).
 * Порт docs/design_transfer/07 (useInView.ts).
 */
export function useInView(threshold = 0.14, rootMargin = "0px", once = true) {
  const ref = useRef(null);
  const [inView, setInView] = useState(() => isFigmaCaptureMode());

  useEffect(() => {
    if (isFigmaCaptureMode()) {
      setInView(true);
      return undefined;
    }
    const el = ref.current;
    if (!el) return undefined;
    if (!("IntersectionObserver" in window)) {
      setInView(true);
      return undefined;
    }

    // Блок выше экрана физически не может показать `threshold` СВОЕЙ площади:
    // документ на 7600px при экране 844px показывает максимум 11% — при пороге
    // 14% обсервер не срабатывает НИКОГДА, и контент навсегда остаётся
    // скрытым (так целиком пропадала страница юр-документов на мобильном).
    // Для таких блоков порог считаем от высоты ЭКРАНА: «блок вошёл во вьюпорт
    // на threshold его высоты» — семантика та же, но достижимая при любом росте.
    const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
    const elH = el.getBoundingClientRect().height;
    const unreachable = viewportH > 0 && elH * threshold > viewportH * 0.9;
    const options = unreachable
      ? { threshold: 0, rootMargin: `0px 0px -${Math.round(threshold * 100)}% 0px` }
      : { threshold, rootMargin };

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setInView(true);
        // one-shot: для reveal-анимаций возврат в false не нужен и только
        // заставлял бы контент мигать при обратной прокрутке.
        if (once) observer.disconnect();
      } else if (!once) {
        // `once: false` — для того, что должно ОСТАНАВЛИВАТЬСЯ за экраном
        // (авто-циклы, таймеры): иначе они крутятся до конца сессии.
        setInView(false);
      }
    }, options);
    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold, rootMargin, once]);

  return [ref, inView];
}
