/**
 * Glass-примитив InCellCorp (JS-порт рецептов 05/06 из docs/design_transfer).
 *
 * Chakra-prop объекты, которые компоненты спредят на поверхности:
 *   <Box {...GLASS_CARD_BASE} _after={CARD_TOP_LINE} _hover={CARD_HOVER_STATE} />
 *
 * Иридесцентное стекло = полупрозрачная заливка (glass.bg) + iris-бордер +
 * backdrop-blur (с -webkit-) + мягкая тень; на hover — подъём, ярче бордер/фон,
 * глубже тень + iris-bloom и выезжающая радужная top-line.
 *
 * Лестница hover-глубины: микро-элементы −1px, малые карты −2px, карты −4px.
 *
 * Лежит в theme/ (а не shared/ui/), чтобы фичи могли импортировать через
 * @theme/glass — ESLint запрещает фичам тянуть пути с сегментом ui.
 */
import { colors, shadows, gradients, motion, borderRadius } from "./tokens";

const { glass, aura, fg, blue } = colors;

export const CARD_TRANSITION =
  `transform 200ms ${motion.easeOut}, border-color 200ms ${motion.easeOut}, ` +
  `background 200ms ${motion.easeOut}, box-shadow 200ms ${motion.easeOut}`;

// Примечание: `backdropFilter` как Chakra-проп автопрефиксится emotion/stylis
// (в выводе появляется `-webkit-backdrop-filter` для Safari), поэтому отдельный
// ключ `WebkitBackdropFilter` не нужен — как top-level Chakra-проп он не
// распознаётся и протекает в DOM (React-варнинг).

/** Минимальная стеклянная поверхность (нав/панель/дровер). */
export const GLASS_SURFACE = {
  background: glass.bg,
  border: `1px solid ${glass.border}`,
  boxShadow: shadows.glassCard,
  backdropFilter: `blur(${glass.blur})`,
  borderRadius: borderRadius.lg,
};

/** Усиленное стекло для модалок/нав (блюр 22px). */
export const GLASS_SURFACE_STRONG = {
  ...GLASS_SURFACE,
  backdropFilter: `blur(${glass.blurStrong})`,
};

/** База glass-карты: iris-аура поверх стекла + переход (спредить на position:relative). */
export const GLASS_CARD_BASE = {
  position: "relative",
  overflow: "hidden",
  background: `${aura.iris}, ${glass.bg}`,
  border: `1px solid ${glass.border}`,
  boxShadow: shadows.glassCard,
  backdropFilter: `blur(${glass.blur})`,
  borderRadius: borderRadius.lg,
  transition: CARD_TRANSITION,
};

/**
 * Радужная 1px линия у верхней кромки карты — скрыта до hover и «выезжает»
 * по горизонтали (inset 28px → 12px), а не просто проявляется. Кладётся в `_after`.
 */
export const CARD_TOP_LINE = {
  content: '""',
  position: "absolute",
  top: 0,
  left: "28px",
  right: "28px",
  height: "1px",
  background: gradients.cardTopLine,
  opacity: 0,
  transition: `opacity 300ms ${motion.easeOut}, left 300ms ${motion.easeOut}, right 300ms ${motion.easeOut}`,
  pointerEvents: "none",
};

/** Состояние hover карты (−4px + микро-scale, ярче бордер/фон, lift-тень, выезд top-line). */
export const CARD_HOVER_STATE = {
  transform: "translateY(-4px) scale(1.008)",
  borderColor: glass.borderHi,
  background: `${aura.iris}, ${glass.bg2}`,
  boxShadow: shadows.glassLift,
  _after: { opacity: 1, left: "12px", right: "12px" },
};

/** Лёгкий hover для малых карт/строк (−2px). */
export const CARD_HOVER_SOFT = {
  transform: "translateY(-2px)",
  borderColor: glass.borderHi,
  background: `${aura.iris}, ${glass.bg2}`,
  boxShadow: shadows.glassCard,
};

/** База инпута/текстареа: стекло + iris-бордер + синий focus (06-components.md). */
export const INPUT_BASE = {
  w: "100%",
  border: `1px solid ${glass.border}`,
  borderRadius: borderRadius.sm,
  bg: "rgba(8,10,20,0.55)",
  color: fg[1],
  transition: `border-color 160ms ${motion.easeOut}, background 160ms ${motion.easeOut}`,
  // Фокус ДОЛЖЕН быть виден: раньше здесь стояли outline:none + boxShadow:none,
  // и единственным признаком фокуса оставалась смена цвета рамки с контрастом
  // 1.9:1 — клавиатурный пользователь терял позицию во всех формах (вход,
  // регистрация, код из письма, админка, профиль, поиск чатов).
  _focusVisible: {
    borderColor: blue[300],
    bg: "rgba(8,10,20,0.7)",
    boxShadow: `0 0 0 2px ${blue[300]}`,
  },
  // fg[4] (3.5:1) для плейсхолдера ниже нормы читаемости — берём fg[3] (6.6:1)
  // из той же рампы.
  _placeholder: { color: fg[3] },
};
