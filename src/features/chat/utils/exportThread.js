import { stripThinking } from './thinking';

function fmtTime(ts) {
  const d = ts ? new Date(ts) : null;
  if (!d || Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
}

function slugify(name) {
  return String(name || 'chat')
    .toLowerCase()
    .replace(/[^\wа-яё]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'chat';
}

/** Сериализовать текущий тред в Markdown (то, что реально загружено на клиенте). */
export function buildConversationMarkdown(messages, title) {
  const lines = [];
  lines.push(`# ${title || 'Чат'}`);
  lines.push('');
  lines.push(`_Экспортировано ${fmtTime(new Date().toISOString())} · GPTHub_`);
  lines.push('');
  for (const m of messages || []) {
    if (!m?.content) continue;
    const time = fmtTime(m.timestamp);
    if (m.type === 'user') {
      lines.push(`## 🧑 Пользователь${time ? ` · ${time}` : ''}`);
      lines.push('');
      lines.push(String(m.content).trim());
    } else {
      const model = m.metadata?.selected_model || m.metadata?.model || '';
      lines.push(`## 🤖 Ассистент${model ? ` · ${model}` : ''}${time ? ` · ${time}` : ''}`);
      lines.push('');
      lines.push(stripThinking(String(m.content)).trim());
    }
    lines.push('');
    lines.push('---');
    lines.push('');
  }
  return lines.join('\n');
}

/** Собрать и скачать Markdown-файл текущего треда. Возвращает число сообщений. */
export function exportConversationMarkdown(messages, title) {
  const list = (messages || []).filter((m) => m?.content && String(m.content).trim());
  if (list.length === 0) return 0;
  const md = buildConversationMarkdown(list, title);
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${slugify(title)}.md`;
  a.click();
  URL.revokeObjectURL(url);
  return list.length;
}
