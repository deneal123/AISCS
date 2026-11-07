import { useEffect, useState } from 'react';
import { loadMotorReadout } from './motorReadout';

export default function useMotorReadout(data) {
  const [state, setState] = useState({ source: null, data: null, error: '' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ source: data, data: null, error: '' });
    if (data) loadMotorReadout(data, controller.signal).then(readout => {
      if (!controller.signal.aborted) setState({ source: data, data: readout, error: '' });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ source: data, data: null, error: 'Моторные популяции недоступны. Движение приостановлено; запись и события ЦНС доступны.' });
    });
    return () => controller.abort();
  }, [data, attempt]);
  return { data: state.source === data ? state.data : null, error: state.source === data ? state.error : '', retry: () => setAttempt(value => value + 1) };
}
