import { colors } from "@theme/tokens";

export const clampTraceDetail = (value, max = 180, preserveNewlines = false) => {
  if (!value) return '';
  // preserveNewlines — для блока рассуждений (<think>): схлопываем только
  // пробелы/табы внутри строк и лишние пустые строки, но переносы сохраняем,
  // чтобы reasoning читался абзацами.
  const normalized = preserveNewlines
    ? String(value)
        .replace(/[ \t\f\v]+/g, ' ')
        .replace(/[ \t]*\n[ \t]*/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim()
    : String(value).replace(/\s+/g, ' ').trim();
  if (normalized.length <= max) {
    return normalized;
  }
  return `${normalized.slice(0, max - 3)}...`;
};

const TRACE_NAMES = {
  general: 'Основной агент',
  web_search: 'Веб-поиск',
  deep_research: 'Глубокое исследование',
  image_gen: 'Генерация изображений',
  pptx_gen: 'Создание презентации',
  audio_transcribe: 'Распознавание аудио',
  multimodal: 'Мультимодальный анализ',
  planner: 'Планировщик',
  router: 'Маршрутизатор',
  web_search_tool: 'Поиск в интернете',
  fetch_url: 'Открытие веб-страницы',
  analyze_data: 'Анализ данных',
  search_knowledge_graph: 'Поиск по базе знаний',
  watch_video: 'Анализ видео',
  ws_list: 'Просмотр файлов',
  ws_read: 'Чтение файла',
  ws_grep: 'Поиск по файлам',
  ws_write: 'Запись файла',
  external_tool: 'Внешний инструмент',
};

const OMISSION_REASONS = {
  needs_confirmation: 'нужно ваше согласие',
  missing_data: 'не хватает данных для запуска',
  disabled_by_config: 'отключён в настройках',
  model_no_tool_support: 'выбранная модель не поддерживает инструменты',
  catalog_unknown: 'не удалось проверить поддержку инструментов',
  not_in_tier: 'будет раскрыт при необходимости на следующем шаге',
};

/** Русское отображаемое имя агента или инструмента; техническое имя не выводим как есть. */
export function getTraceName(value, fallback = 'Инструмент') {
  const key = String(value || '').trim().toLowerCase();
  if (!key) return fallback;
  return TRACE_NAMES[key] || `«${key.replace(/[_-]+/g, ' ')}»`;
}

/** Причины пропуска приходят из API как стабильные коды, а не как готовый UI-текст. */
export function getOmissionReason(value) {
  const key = String(value || '').trim().toLowerCase();
  return OMISSION_REASONS[key] || 'недоступен для этого запроса';
}

const EVENT_BADGE = {
  error: { scheme: 'red', accent: colors.error, label: 'Ошибка' },
  done: { scheme: 'gray', accent: colors.fg[2], label: 'Готово' },
  info: { scheme: 'blue', accent: colors.info, label: 'Инфо' },
  thinking: { scheme: 'purple', accent: colors.violet[300], label: 'Размышления' },
  // План решения: свой вид, потому что это не «шаг обработки», а содержательный
  // артефакт — единственное место, где видно, что именно агент собрался делать.
  plan: { scheme: 'cyan', accent: colors.cyan[300], label: 'План' },
  default: { scheme: 'gray', accent: colors.fg[3], label: 'Шаг' },
};

/** Стиль бейджа/акцента для события трейса по его kind. */
export function getEventBadgeStyle(kind) {
  return EVENT_BADGE[kind] || EVENT_BADGE.default;
}

// Стабильные цвета по субагентам — ЕДИНЫЙ источник (colors.agents в токенах),
// та же палитра, что и на витрине /platform (content/platform.js).
const AGENT_COLORS = colors.agents;
const AGENT_PALETTE = colors.agentPalette;
const AGENT_LABELS = {
  general: 'Основной',
  web_search: 'Веб-поиск',
  deep_research: 'Исследование',
  image_gen: 'Изображение',
  pptx_gen: 'Презентация',
  audio_transcribe: 'Аудио',
  multimodal: 'Мультимодальный',
  planner: 'Планировщик',
  router: 'Маршрутизатор',
};

/** Стабильный цвет субагента (известные — фикс, прочие — хеш по палитре). */
export function getAgentColor(agent) {
  if (!agent) return null;
  const key = String(agent).toLowerCase();
  if (AGENT_COLORS[key]) return AGENT_COLORS[key];
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return AGENT_PALETTE[hash % AGENT_PALETTE.length];
}

/** Человекочитаемое имя субагента для бейджа в трейсе. */
export function getAgentLabel(agent) {
  if (!agent) return '';
  const key = String(agent).toLowerCase();
  return AGENT_LABELS[key] || getTraceName(key, 'Агент');
}

/** Производные статуса сессии трейса (running/error/done) для шапки карточки. */
export function getSessionStatus(status) {
  const isRunning = status === 'running';
  const isError = status === 'error';
  return {
    isRunning,
    isError,
    badgeScheme: isError ? 'red' : isRunning ? 'yellow' : 'gray',
    label: isError ? 'Ошибка' : isRunning ? 'В работе' : 'Готово',
  };
}
