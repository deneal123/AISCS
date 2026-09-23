import { COMPANY_NAME, PROJECT_NAME } from "@constants";

/**
 * Брендовые константы и тон голоса — единый источник правды для копирайта.
 * Тон InCellCorp: спокойно, премиально, инженерно, честно, клиентоориентированно.
 * Позиционирование: GPTHub — универсальное рабочее пространство с ИИ (не health).
 */

export const BRAND = {
  product: PROJECT_NAME, // GPTHub
  company: COMPANY_NAME, // InCellCorp
  // Единый тег-лайн (раньше было два расходящихся варианта в footer и auth).
  tagline: "Единое рабочее пространство для всех задач с ИИ",
  taglineShort: "Рабочее пространство с ИИ",
  lockup: `${PROJECT_NAME} · AI Workspace`,
  // Короткое честное описание продукта (для SEO / meta / подзаголовков).
  descriptor:
    "GPTHub — рабочее пространство InCellCorp, где команда ИИ-агентов решает ваши задачи: диалог, поиск в интернете, глубокое исследование, генерация изображений и презентаций — с памятью между сессиями.",
  eyebrow: "GPTHub · AI Workspace",
};
