import { useEffect, useState } from 'react';
import { loadPeripheralReadout } from './peripheralReadout';

export default function usePeripheralReadout(source) {
  const [state, setState] = useState({ source: null, data: null, error: '' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ source, data: null, error: '' });
    if (source) loadPeripheralReadout(source, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ source, data, error: '' });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ source, data: null, error: 'Реестр периферических нервов недоступен. Показана только схема без подсветки событий.' });
    });
    return () => controller.abort();
  }, [source, attempt]);
  return { data: state.source === source ? state.data : null, error: state.source === source ? state.error : '', retry: () => setAttempt(value => value + 1) };
}
