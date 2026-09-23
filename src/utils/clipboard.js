/**
 * Копирование текста в буфер обмена с надёжным фолбэком.
 *
 * `navigator.clipboard` доступен только в secure-context (https или localhost) и
 * не во всех браузерах; раньше сайты копирования писали `navigator.clipboard
 * ?.writeText(...).catch(() => {})` — в незащищённом контексте это молча ничего
 * не делало (юзер жмёт «Копировать», ничего не происходит, обратной связи ноль).
 * Здесь — единый путь: сначала Async Clipboard API, при отказе/отсутствии падаем
 * на legacy `execCommand('copy')` через скрытую textarea.
 *
 * @returns {Promise<boolean>} true, если текст удалось скопировать.
 */
export async function copyText(text) {
  if (text == null) return false;
  const str = String(text);

  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(str);
      return true;
    } catch {
      // Нет доступа / не secure-context — пробуем legacy-путь ниже.
    }
  }

  if (typeof document === 'undefined') return false;
  try {
    const ta = document.createElement('textarea');
    ta.value = str;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-9999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export default copyText;
