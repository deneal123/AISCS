import { useCallback, useEffect, useRef, useState } from 'react';

export const LIBRARY_PAGE_SIZE = 10;

/** Серверные страницы библиотеки: результаты не накапливаются в памяти клиента. */
export function useLibraryBrowser({ enabled, revision }) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [composing, setComposing] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [result, setResult] = useState({ items: [], page: 0, query: '', hasMore: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const previousQuery = useRef('');
  const search = useCallback((value) => { setQuery(value); setPage(0); }, []);
  const refresh = useCallback(() => setRefreshVersion(value => value + 1), []);

  useEffect(() => {
    if (!enabled || composing) return undefined;
    const controller = new AbortController();
    let retired = false;
    const q = query.trim();
    const delay = q && q !== previousQuery.current ? 300 : 0;
    setLoading(true);
    setError(false);
    const timer = setTimeout(async () => {
      previousQuery.current = q;
      try {
        const { getAccountWorkLibrary } = await import('@api/chat');
        if (retired) return;
        const data = await getAccountWorkLibrary({
          params: { limit: LIBRARY_PAGE_SIZE, offset: page * LIBRARY_PAGE_SIZE, q },
          signal: controller.signal,
        });
        if (retired) return;
        if (!Array.isArray(data?.items) || data.items.length > LIBRARY_PAGE_SIZE
          || data.state === 'unavailable') throw new Error('library_page_unavailable');
        // После удаления последней записи возвращаемся на предыдущую страницу.
        if (page > 0 && data.items.length === 0) { setPage(page - 1); return; }
        setResult({ items: data.items, page, query: q,
          hasMore: data.next_offset != null || data.next_cursor != null });
      } catch {
        if (!retired) setError(true);
      } finally {
        if (!retired) setLoading(false);
      }
    }, delay);
    return () => { retired = true; clearTimeout(timer); controller.abort(); };
  }, [enabled, composing, query, page, revision, refreshVersion]);

  const matching = result.query === query.trim();
  return { query, search, setComposing, loading, error, refresh,
    items: matching ? result.items : [], page: matching ? result.page : 0,
    hasMore: matching && result.hasMore, goToPage: setPage };
}
