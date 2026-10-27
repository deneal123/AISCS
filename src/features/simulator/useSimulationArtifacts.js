import { useEffect, useState } from 'react';
import { simulationApi } from './api';

export default function useSimulationArtifacts(runId, state, enabled) {
  const [files, setFiles] = useState([]), [loading, setLoading] = useState(false);
  const [error, setError] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setFiles([]); setError(''); setLoading(false);
    if (!enabled || !runId || state !== 'completed') return () => controller.abort();
    setLoading(true);
    simulationApi.artifacts(runId, controller.signal).then(result => {
      if (!controller.signal.aborted) setFiles(result.items);
    }).catch(() => {
      if (!controller.signal.aborted) setError('Не удалось загрузить файлы опыта. Повторите загрузку.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, state, enabled, retry]);
  return { files, loading, error, retry: () => setRetry(value => value + 1) };
}
