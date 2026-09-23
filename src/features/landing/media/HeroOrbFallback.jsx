import React from "react";

/**
 * CSS-фолбэк героя — показывается, когда WebGL off/reduced-no-webgl/reduced-motion
 * или three не загрузился. Всегда отгружается (docs/design_transfer/09). Стили —
 * `.hero-orb-fallback*` в src/styles/motion.css.
 */
export default function HeroOrbFallback() {
  return (
    <div className="hero-orb-fallback" aria-hidden>
      <span className="hero-orb-fallback-sheen" />
    </div>
  );
}
