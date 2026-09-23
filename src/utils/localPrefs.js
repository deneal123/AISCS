/**
 * Тонкая обёртка над localStorage для персистентных настроек (напр. fx-tier).
 * Никогда не бросает (приватный режим / отключённый storage).
 */
export function localPrefGet(key, fallback = null) {
  try {
    if (typeof window === "undefined") return fallback;
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : raw;
  } catch {
    return fallback;
  }
}

export function localPrefSet(key, value) {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(key, String(value));
  } catch {
    /* no-op */
  }
}
