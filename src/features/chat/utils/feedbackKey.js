/**
 * FNV-1a (32-bit) по UTF-8-байтам обрезанного контента → 8 hex-символов.
 * ОБЯЗАН совпадать 1:1 с backend feedback_store.feedback_key (Python), т.к.
 * фидбэк 👍/👎 хранится по контент-ключу (у live-сообщений нет серверного id).
 *
 * UTF-8 кодируем вручную (не через TextEncoder) — чтобы работать одинаково в
 * браузере, jsdom и node без внешних полифиллов.
 */
function utf8Bytes(str) {
  const bytes = [];
  for (let i = 0; i < str.length; i += 1) {
    let code = str.charCodeAt(i);
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code >= 0xd800 && code <= 0xdbff) {
      // суррогатная пара → кодовая точка > 0xFFFF (4 байта)
      const hi = code;
      const lo = str.charCodeAt(i + 1);
      i += 1;
      code = 0x10000 + ((hi - 0xd800) << 10) + (lo - 0xdc00);
      bytes.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
    } else {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    }
  }
  return bytes;
}

export function feedbackKey(content) {
  const bytes = utf8Bytes(String(content || '').trim());
  let h = 0x811c9dc5;
  for (let i = 0; i < bytes.length; i += 1) {
    h ^= bytes[i];
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}
