// Извлечение «рассуждений» модели из её вывода.
//
// Многие модели (aion, deepseek-r1, qwen-thinking и т.п.) оборачивают цепочку
// рассуждений в теги <think>...</think> и затем выдают финальный ответ. Эти
// токены НЕ должны попадать в тело сообщения — их место в trace-панели
// («Ход рассуждения»). Здесь мы делим сырой вывод на:
//   visible   — то, что показываем пользователю (без блоков <think>),
//   reasoning — собранный текст рассуждений (для trace-панели).
//
// Парсер устойчив к стримингу: незакрытый хвостовой <think> (модель ещё
// генерирует рассуждение) целиком уходит в reasoning, а visible остаётся
// пустым/обрезанным — пузырь не «протекает» сырым reasoning во время потока.

const THINK_BLOCK = /<think\b[^>]*>([\s\S]*?)<\/think>/gi;
const THINK_OPEN_UNCLOSED = /<think\b[^>]*>([\s\S]*)$/i;
const EMPTY = { visible: '', reasoning: '' };

export function parseThinking(raw) {
  if (!raw || typeof raw !== 'string') return { ...EMPTY, visible: raw || '' };
  // Быстрый выход: нет тега <think> — чинить нечего.
  if (raw.indexOf('<think') === -1) return { visible: raw, reasoning: '' };

  const reasoningParts = [];
  let visible = raw.replace(THINK_BLOCK, (_match, inner) => {
    const trimmed = (inner || '').trim();
    if (trimmed) reasoningParts.push(trimmed);
    return '';
  });

  // Незакрытый <think> в конце (активный стрим рассуждений).
  const open = visible.match(THINK_OPEN_UNCLOSED);
  if (open) {
    const trimmed = (open[1] || '').trim();
    if (trimmed) reasoningParts.push(trimmed);
    visible = visible.slice(0, open.index);
  }

  return { visible: visible.trim(), reasoning: reasoningParts.join('\n\n').trim() };
}

/** Только видимая часть (без рассуждений) — для рендера/копирования. */
export function stripThinking(raw) {
  return parseThinking(raw).visible;
}

// Сырые теги вызова инструмента, которые слабые модели (напр. claude-3/haiku через
// агрегатор) иногда ПЕЧАТАЮТ ТЕКСТОМ в ответ вместо нативного tool-call: блоки
// <function_calls><invoke name="..."><parameter>...</parameter></invoke></function_calls>.
// Пользователю это мусор — реальный вызов инструмента идёт своим каналом (trace-панель).
// Незакрытый хвост при стриме тоже режем, чтобы пузырь не «протекал» сырой разметкой.
const TOOL_CALL_BLOCK = /<function_calls>[\s\S]*?<\/function_calls>/gi;
const TOOL_CALL_UNCLOSED = /<function_calls>[\s\S]*$/i;

/** Убрать сырые function-call теги из видимого текста (не трогает нормальный markdown).
 *
 * ⚠️ НЕ РЕЖЕМ ВНУТРИ КОДА. Если пользователь просит показать пример function-call тега,
 * агент отвечает им в код-блоке (```…```) или инлайн-коде (`…`) — это легитимный контент,
 * а не сырой tool-call модели. Резали бы везде — такой пример превращался бы в пустой
 * код-блок (потеря данных). Сегментируем текст на код/не-код (как normalizeMath) и режем
 * теги ТОЛЬКО в не-код сегментах. */
export function stripToolCallTags(raw) {
  if (!raw || typeof raw !== 'string' || raw.indexOf('<function_calls') === -1) {
    return raw || '';
  }
  const segments = raw.split(/(```[\s\S]*?```|`[^`]*`)/g);
  return segments
    .map((seg, i) => {
      if (i % 2 === 1) return seg; // код-сегмент — сохраняем как есть
      return seg.replace(TOOL_CALL_BLOCK, '').replace(TOOL_CALL_UNCLOSED, '');
    })
    .join('');
}
