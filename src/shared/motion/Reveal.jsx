import React from "react";
import { useInView } from "@hooks/useInView";
import { cx } from "@utils/motion";

/**
 * Scroll-reveal обёртка: добавляет класс `.in`, когда блок появляется во
 * вьюпорте (one-shot), CSS делает анимацию (см. src/styles/motion.css).
 * Варианты: default (18px) / deep (32px, крупные секции) / soft (10px) /
 * rise (26px + scale + de-blur, герой/фичи). Для каскада детей добавить
 * className="stagger-children" (анимируются ПРЯМЫЕ дети).
 * Порт docs/design_transfer/07 (Reveal.tsx) в JS.
 *
 * Живёт в shared/motion (не shared/ui), чтобы фичи могли импортировать:
 * ESLint запрещает фичам тянуть пути с сегментом ui.
 */
export function Reveal({
  delay = 0,
  children,
  as: Component = "div",
  className = "",
  style,
  threshold = 0.14,
  variant,
  rootMargin = "0px",
  ...rest
}) {
  const [ref, inView] = useInView(threshold, rootMargin);
  return (
    <Component
      ref={ref}
      className={cx("in-view-reveal", inView && "in", className)}
      style={{ transitionDelay: `${delay}ms`, ...style }}
      data-reveal-variant={variant}
      {...rest}
    >
      {children}
    </Component>
  );
}

export default Reveal;
