import { useCallback, useMemo, useState } from 'react';

const KEY = 'gpthub:chat:pinned';

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.map(String) : [];
  } catch {
    return [];
  }
}

/**
 * Закрепление тредов — личное UI-предпочтение, храним клиентски (localStorage).
 * Множество id + toggle; порядок закрепления сохраняется (новые сверху).
 */
export function usePinnedThreads() {
  const [pinned, setPinned] = useState(() => load());
  const pinnedIds = useMemo(() => new Set(pinned), [pinned]);

  const togglePin = useCallback((id) => {
    const key = String(id);
    setPinned((prev) => {
      const next = prev.includes(key) ? prev.filter((x) => x !== key) : [key, ...prev];
      try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* quota/private mode — non-critical */ }
      return next;
    });
  }, []);

  return { pinnedIds, togglePin };
}
