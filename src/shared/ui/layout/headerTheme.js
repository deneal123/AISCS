import { colors } from "@theme/tokens";

const { accent, glass } = colors;

/** Палитра шапки — общая для Header / HeaderUserMenu / HeaderMobileMenu.
 *  Брендовые значения ссылаются на токены; нейтральные white/dark-alpha —
 *  осознанные литералы (точных токенов под эти альфы нет). */
export const HEADER_THEME = {
  // База — чистый чёрный, как в Nav эталона (rgba(0,0,0,.68) + blur 20).
  // Была rgba(6,7,12,…): сине-чёрная и светлее, из-за чего сквозь неё
  // пробивался яркий фон и шапка читалась «поднятой».
  bg: "rgba(0, 0, 0, 0.72)",
  bgScrolled: "rgba(0, 0, 0, 0.88)",
  border: glass.border, // rgba(140,160,255,0.16) — было дублем литералом
  borderSoft: "rgba(140, 160, 255, 0.10)", // мягкий iris-тинт бордера
  text: "rgba(255, 255, 255, 0.9)",
  muted: "rgba(255, 255, 255, 0.62)",
  accent: accent.base, // #2D5BFF
  accentSoft: accent.soft, // rgba(45,91,255,0.12)
};
