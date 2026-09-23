import { BRAND } from "./brand";

/**
 * Общий копирайт: футер, статусы. Тег-лайн сведён к единому варианту (BRAND.tagline).
 */

export const FOOTER_COPY = {
  tagline: BRAND.tagline,
  // Строка о компании — InCellCorp раньше не упоминался нигде в UI.
  company: `${BRAND.product} — продукт ${BRAND.company}.`,
  status: { online: "Online", offline: "Не в сети" },
};
