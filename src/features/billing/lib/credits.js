// Чистые помощники биллинга (без зависимостей от React/Chakra) — легко тестируются.
import { colors } from '@theme/tokens';

const RU = new Intl.NumberFormat('ru-RU');

export const formatCredits = (value) => RU.format(Math.max(0, Math.round(Number(value) || 0)));

export const formatRub = (value) => `${RU.format(Math.round(Number(value) || 0))} ₽`;

// Компактный формат токенов: 950 → «950», 12345 → «12.3K», 2100000 → «2.1M».
const TOKENS_FMT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
export const formatTokens = (value) => {
  const n = Math.max(0, Math.round(Number(value) || 0));
  return n < 1000 ? String(n) : TOKENS_FMT.format(n);
};

// Пользовательские ₽ = billed ₽ = credits × credit_unit_rub. rate отсутствует
// (старый бэкенд / не сконфигурирован) → null, вызывающий скрывает ₽-строку.
export const rubFromCredits = (credits, rate) => {
  const r = Number(rate);
  if (!Number.isFinite(r) || r <= 0) return null;
  return formatRub(Math.max(0, Number(credits) || 0) * r);
};

// Доля в процентах (целое, 0..100), защищённая от деления на ноль.
export const pct = (value, total) => {
  const t = Number(total) || 0;
  if (t <= 0) return 0;
  return Math.round((Math.max(0, Number(value) || 0) / t) * 100);
};

// Человекочитаемые ярлыки моделей: id вида "openai/gpt-4o" → "gpt-4o".
export const MODEL_LABELS = { unknown: 'Неизвестно' };
export const modelLabel = (id) => {
  if (id == null || id === '') return 'Неизвестно';
  const key = String(id);
  if (MODEL_LABELS[key]) return MODEL_LABELS[key];
  const slash = key.indexOf('/');
  return slash > 0 ? key.slice(slash + 1) : key;
};

// Ярлыки типов операций (ключи маршрутизатора инструментов из by_agent).
export const AGENT_LABELS = {
  general: 'Общий чат',
  none: 'Общий чат',
  web_search: 'Веб-поиск',
  deep_research: 'Глубокое исследование',
  image_gen: 'Генерация изображений',
  audio_transcribe: 'Транскрипция аудио',
  pptx_gen: 'Презентация',
};
export const agentLabel = (key) => {
  if (key == null || key === '') return 'Общий чат';
  const k = String(key);
  if (AGENT_LABELS[k]) return AGENT_LABELS[k];
  return k.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
};

export const PLAN_LABELS = { free: 'Free', pro: 'Pro', enterprise: 'Enterprise' };

export const planLabel = (plan) => PLAN_LABELS[plan] || (plan ? String(plan) : 'Free');

export const CREDIT_COLORS = { ok: colors.blue[500], warn: colors.warning, danger: colors.error };

// Гейдж ОСТАТКА подписочного кошелька: {percent, color} — доля остатка (100=полный
// кошелёк, 0=потрачено), цвет по уровню остатка. Раньше полоса показывала
// ПОТРАЧЕНО: заполнялась к концу и была ПОЛНОСТЬЮ КРАСНОЙ при «0 осталось» —
// читалось наоборот (полный бар = будто кошелёк полон). Теперь как топливный
// датчик: убывает по мере трат, пустеет к нулю.
export const creditBarView = (used, limit) => {
  const lim = Number(limit) || 0;
  const usedN = Math.max(0, Number(used) || 0);
  if (lim <= 0) return { percent: 0, color: CREDIT_COLORS.ok };
  const remaining = Math.max(0, lim - usedN);
  const percent = Math.min(100, Math.round((remaining / lim) * 100));
  let color = CREDIT_COLORS.ok; // здоровый остаток — синий (бренд-акцент)
  if (percent <= 5) color = CREDIT_COLORS.danger; // почти пусто — красный
  else if (percent <= 25) color = CREDIT_COLORS.warn; // мало — оранжевый
  return { percent, color };
};

// Уровень остатка для индикатора в composer.
export const creditLevel = (total, lowThreshold = 5000) => {
  const value = Number(total) || 0;
  if (value <= 0) return 'empty';
  if (value < lowThreshold) return 'low';
  return 'ok';
};

export const EVENT_LABELS = {
  usage: 'Списание',
  topup: 'Пополнение',
  subscription_grant: 'Подписка',
  refund: 'Возврат',
  adjustment: 'Корректировка',
};

export const eventLabel = (type) => EVENT_LABELS[type] || (type ? String(type) : '—');
