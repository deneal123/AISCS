/**
 * Общие Chakra-prop рецепты (не привязаны к стеклянным поверхностям —
 * см. theme/glass.js для тех). Живёт в theme/, чтобы фичи могли импортировать
 * через @theme/styles — ESLint запрещает фичам тянуть пути с сегментом ui.
 */
import { colors, typography } from "./tokens";

const { accent } = colors;

/** Единый микролейбл: mono, uppercase, один размер — вместо разрозненных 10/10.5/11px. */
export const MICRO_LABEL_SX = {
  fontSize: "10.5px",
  fontWeight: 600,
  fontFamily: typography.fontFamily.mono,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: colors.fg[4],
};

/** Синяя "ghost"-кнопка: фон/бордер/hover — было скопировано литералами в 5+ мест. */
export const GHOST_BUTTON_BLUE_SX = {
  bg: accent.subtle,
  color: accent.subtleText,
  border: `1px solid ${accent.subtleBorder}`,
  _hover: { bg: accent.subtleHover },
};

/** Синий бейдж/чип без интерактивных состояний (та же заливка, без бордера/hover). */
export const GHOST_BADGE_BLUE_SX = {
  bg: accent.subtle,
  color: accent.subtleText,
};
