/** Структурированная история показывается как диалог, а не как транспортный JSON. */
export function memoryDisplayText(value) {
  const original = String(value || '').trim();
  if (original.length > 200000) return original;
  // В префиксе бывает дата в скобках. JSON начинается только с роли или массива.
  const jsonStart = original.search(/\{\s*"role"\s*:|\[\s*\{\s*"role"\s*:/);
  if (jsonStart < 0) return original;
  const prefix = original.slice(0, jsonStart).trim();
  const source = original.slice(jsonStart);
  const roles = { user: 'Вы', assistant: 'Ассистент', system: 'Инструкция' };
  try {
    const parsed = JSON.parse(source.startsWith('[') ? source : `[${source}]`);
    if (!Array.isArray(parsed) || !parsed.length || !parsed.every(item => (
      item && Object.hasOwn(roles, item.role) && typeof item.content === 'string'
    ))) return original;
    return [prefix, ...parsed.map(item => `${roles[item.role]}: ${item.content}`)]
      .filter(Boolean).join('\n\n');
  } catch {
    return original;
  }
}

export function extractMemosMemories(dashboard) {
  if (!dashboard || typeof dashboard !== 'object') return [];
  const out = [];
  for (const group of ['text_mem', 'pref_mem', 'tool_mem', 'skill_mem']) {
    if (!Array.isArray(dashboard[group])) continue;
    for (const cube of dashboard[group]) {
      if (!Array.isArray(cube?.memories)) continue;
      for (const memory of cube.memories) {
        const text = typeof memory === 'string' ? memory
          : memory?.memory || memory?.text || memory?.content || memory?.summary;
        if (typeof text === 'string' && text.trim()) out.push(text.trim());
      }
    }
  }
  return out;
}
