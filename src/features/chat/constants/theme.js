import { colors, gradients } from '@theme/tokens';
import { INPUT_BASE } from '@theme/glass';

/**
 * Тема чата — ПРОИЗВОДНАЯ от дизайн-системы InCellCorp (@theme/tokens +
 * @theme/glass), а не параллельный форк. Единый источник истины: семантические
 * ключи сохранены (их читают ~14 компонентов чата), но значения ссылаются на
 * токены — это устраняет дрейф (было panelBorder .14 vs glass.border .16,
 * off-ramp pageBg #05070d и т.п.). Полноценные стеклянные поверхности собираются
 * из @theme/glass (GLASS_SURFACE / GLASS_CARD_BASE / INPUT_BASE) прямо в
 * компонентах; здесь — только плоские семантические значения.
 */
export const CHAT_FONT_FAMILY = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

const { glass, accent, fg, ink, bg } = colors;

export const CHAT_THEME = {
  // Базовая тёмная канва — на ink-рампе дизайн-системы (было off-ramp #05070d).
  pageBg: ink[950],
  pageGradient: `${gradients.midnightMesh}, ${ink[950]}`,

  // Стеклянные поверхности (панели/сайдбар).
  panelBg: glass.bg, // rgba(16,20,38,0.55)
  sidebarBg: bg.chrome, // rgba(12,15,28,0.72) — «шасси» сайдбара, глубже панелей
  panelBorder: glass.border, // .16 (было .14 — дрейф устранён)
  panelBorderStrong: glass.borderHi, // .34 (было .26)
  panelHover: glass.hover, // rgba(140,160,255,0.08) — iris-тинт
  panelActive: glass.active, // rgba(140,160,255,0.14)

  // Пузырь пользователя / прозрачная проза ассистента.
  userBubble: accent.subtle, // rgba(45,91,255,0.16)
  userBubbleBorder: accent.subtleBorder, // rgba(45,91,255,0.30)
  agentBubble: 'transparent',
  agentBubbleBorder: 'transparent',

  // Инпуты композера/поиска — из INPUT_BASE.
  inputBg: INPUT_BASE.bg, // rgba(8,10,20,0.55)
  inputBorder: glass.border,
  inputBorderFocus: INPUT_BASE._focusVisible.borderColor, // blue[300]
  inputStickyBg: bg.sticky, // rgba(6,8,14,0.92) — почти непрозрачная подложка липкого композера

  headerBg: bg.header, // rgba(8,10,18,0.82)

  // Акцент — единственный сплошной синий.
  accent: accent.base, // #2D5BFF
  accentHover: accent.hover, // #1E47E6
  accentSoft: accent.subtle, // rgba(45,91,255,0.16)
  accentGlow: accent.focusRing, // rgba(45,91,255,0.15)

  // Текст — прохладная fg-рампа дизайн-системы.
  textPrimary: fg[1], // #FFFFFF
  textSecondary: fg[3], // #8A90A2
  textTertiary: fg[4], // #5C6376
};

export const CHAT_SCROLLBAR_SX = {
  scrollbarGutter: 'stable',
};
