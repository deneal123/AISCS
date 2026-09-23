/**
 * Общие стиль-константы дроверов (Settings / Memory / Profile живут в разных
 * фичах, поэтому общий JSX-компонент в shared/ui запрещён ESLint — делим стилем).
 * Импорт: `@theme/drawer` (фичам разрешено тянуть @theme/*).
 */

/**
 * Затемнение под дровером. Без backdrop-filter: полноэкранный blur поверх
 * «стеклянной» страницы пере-растеризуется каждый кадр во время слайда и
 * сильно тормозит — тёмный скрим даёт тот же визуальный отрыв без GPU-нагрузки.
 */
export const DRAWER_OVERLAY_PROPS = { bg: 'rgba(0,0,0,0.72)' };

/** Touch-safe close control while retaining the compact desktop drawer chrome. */
export const DRAWER_CLOSE_BUTTON_PROPS = {
  boxSize: { base: '44px', md: '32px' },
  minW: { base: '44px', md: '32px' },
};

/**
 * Фон выезжающей панели дровера. Почти непрозрачный → не требует backdrop-blur
 * (который при slide-анимации даёт сильный jank). Iris-тинт + radial поверх
 * сохраняют стеклянный вид без пере-растеризации блюра каждый кадр.
 */
export const DRAWER_CONTENT_BG = 'rgba(9, 12, 22, 0.97)';

/** Иридесцентный radial-фон контента дровера (углы). */
export const DRAWER_RADIAL_BG =
  'radial-gradient(circle at 85% -10%, rgba(45, 91, 255,0.12), transparent 55%), ' +
  'radial-gradient(circle at 15% 110%, rgba(30, 71, 230,0.08), transparent 50%)';
