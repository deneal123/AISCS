import { useEffect, useState } from 'react';
import { loadSensoryArbors } from './sensoryArbors';

export default function useSensoryArbors(data, enabled) {
  const [state, setState] = useState({ data: null, source: null, loading: false, error: '' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ data: null, source: data, loading: Boolean(data && enabled), error: '' });
    if (data && enabled) loadSensoryArbors(data, controller.signal).then(arbors => {
      if (!controller.signal.aborted) setState({ data: arbors, source: data, loading: false, error: '' });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ data: null, source: data, loading: false, error: 'Не удалось загрузить реконструкции входной популяции. Точки и журнал событий доступны.' });
    });
    return () => controller.abort();
  }, [data, enabled, attempt]);
  return { ...state, data: state.source === data ? state.data : null, retry: () => setAttempt(value => value + 1) };
}
