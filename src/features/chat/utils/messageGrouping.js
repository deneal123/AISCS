/**
 * Группировка сообщений и метки дат — без внешних зависимостей (date-fns в проекте
 * не установлен, из-за чего этот util раньше был un-importable). Русские метки
 * через нативный Intl.
 */

function startOfDay(value) {
  const d = value instanceof Date ? new Date(value) : new Date(value);
  d.setHours(0, 0, 0, 0);
  return d;
}

const WEEKDAY_FMT = new Intl.DateTimeFormat('ru-RU', { weekday: 'long' });
const FULL_FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });

/** «Сегодня» / «Вчера» / день недели (в пределах недели) / полная дата. */
export function getDateLabel(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const today = startOfDay(new Date());
  const that = startOfDay(d);
  const diffDays = Math.round((today.getTime() - that.getTime()) / 86400000);
  if (diffDays <= 0) return 'Сегодня';
  if (diffDays === 1) return 'Вчера';
  if (diffDays < 7) {
    const label = WEEKDAY_FMT.format(d);
    return label.charAt(0).toUpperCase() + label.slice(1);
  }
  return FULL_FMT.format(d);
}

/** Один ли календарный день у двух timestamp'ов. */
export function isSameDay(a, b) {
  const da = a instanceof Date ? a : new Date(a);
  const db = b instanceof Date ? b : new Date(b);
  if (Number.isNaN(da.getTime()) || Number.isNaN(db.getTime())) return false;
  return startOfDay(da).getTime() === startOfDay(db).getTime();
}

export function groupMessagesBySender(messages) {
  if (!messages || messages.length === 0) return [];

  const groups = [];
  let currentGroup = {
    sender: messages[0].type,
    messages: [messages[0]],
  };

  for (let i = 1; i < messages.length; i++) {
    const message = messages[i];

    if (message.type === currentGroup.sender) {
      currentGroup.messages.push(message);
    } else {
      groups.push(currentGroup);
      currentGroup = {
        sender: message.type,
        messages: [message],
      };
    }
  }

  groups.push(currentGroup);

  return groups;
}
