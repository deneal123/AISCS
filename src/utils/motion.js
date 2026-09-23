/**
 * Motion gates — каждая JS/rAF/WebGL-анимация обязана свериться с ними.
 * Порт из docs/design_transfer/07-motion-and-scroll.md (utils.ts) в JS.
 *
 * CSS-killswitch (в theme.js) гасит только CSS-анимации/переходы; JS-моушн
 * (rAF, WebGL, magnetic) им НЕ покрывается — гейтить здесь.
 */

/** Режим захвата (Figma/скриншот) — мгновенно показывать финальное состояние. */
export function isFigmaCaptureMode() {
  return (
    typeof window !== "undefined" &&
    window.location.hash.includes("figmacapture=")
  );
}

/** Пользователь просит меньше движения (или мы в capture-режиме). */
export function prefersReducedMotion() {
  if (typeof window === "undefined") return true;
  if (isFigmaCaptureMode()) return true;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/** Грубый указатель (тач) — пропускать pointer-only моушн (magnetic и т.п.). */
export function isCoarsePointer() {
  if (typeof window === "undefined") return true;
  return window.matchMedia?.("(pointer: coarse)").matches ?? false;
}

/** Классы: cx("a", cond && "b") → "a b". */
export function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}
