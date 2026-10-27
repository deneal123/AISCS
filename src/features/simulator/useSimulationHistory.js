import { useCallback, useEffect, useRef, useState } from 'react';
import { simulationApi } from './api';

export default function useSimulationHistory() {
  const [runs, setRuns] = useState([]), [nextOffset, setNextOffset] = useState(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState('');
  const request = useRef(null), revision = useRef(0), mounted = useRef(true), failed = useRef(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; revision.current += 1; request.current?.abort(); };
  }, []);
  const replace = useCallback(page => {
    revision.current += 1; request.current?.abort(); request.current = null;
    failed.current = null;
    setRuns(page.items); setNextOffset(page.next_offset ?? null); setLoading(false); setError('');
  }, []);
  const read = useCallback(async (offset, append) => {
    request.current?.abort();
    const controller = new AbortController(), version = ++revision.current;
    request.current = controller; failed.current = null; setLoading(true); setError('');
    try {
      const page = await simulationApi.list(controller.signal, offset);
      if (!mounted.current || controller.signal.aborted || version !== revision.current) return;
      setRuns(previous => {
        if (!append) return page.items;
        const known = new Set(previous.map(item => item.id));
        return [...previous, ...page.items.filter(item => !known.has(item.id))];
      });
      setNextOffset(page.next_offset ?? null);
    } catch {
      if (mounted.current && !controller.signal.aborted && version === revision.current) {
        failed.current = [offset, append];
        setError('Не удалось загрузить список опытов. Повторите загрузку.');
      }
    } finally {
      if (mounted.current && version === revision.current) { setLoading(false); request.current = null; }
    }
  }, []);
  const refresh = useCallback(() => read(0, false), [read]);
  const more = () => { if (!loading && nextOffset !== null) return read(nextOffset, true); };
  const retry = () => failed.current && read(...failed.current);
  return { runs, replace, refresh, more, retry, loading, error, nextOffset };
}
