import { useEffect, useState } from 'react';
import { simulationApi } from '../api';

export default function useSimulationArtifacts(runId, state, enabled) {
  const [snapshot, setSnapshot] = useState({ owner: null, files: [], loading: false, error: '' });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setSnapshot({ owner: runId, files: [], loading: false, error: '' });
    if (!enabled || !runId || state !== 'completed') return () => controller.abort();
    setSnapshot({ owner: runId, files: [], loading: true, error: '' });
    simulationApi.artifacts(runId, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      const items = result?.items;
      if (!Array.isArray(items) || items.some(file => !file || typeof file.id !== 'string' || !file.id
          || typeof file.name !== 'string' || !file.name || !Number.isSafeInteger(file.bytes) || file.bytes < 0
          || typeof file.sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(file.sha256))
          || new Set(items.map(file => file.id)).size !== items.length) throw new Error('invalid_artifacts');
      setSnapshot({ owner: runId, files: items, loading: false, error: '' });
    }).catch(() => {
      if (!controller.signal.aborted) setSnapshot({ owner: runId, files: [], loading: false,
        error: 'Не удалось загрузить файлы опыта. Повторите загрузку.' });
    });
    return () => controller.abort();
  }, [runId, state, enabled, retry]);
  const eligible = Boolean(enabled && runId && state === 'completed');
  const visible = eligible && snapshot.owner === runId ? snapshot
    : { files: [], loading: eligible, error: '' };
  return { files: visible.files, loading: visible.loading, error: visible.error,
    retry: () => setRetry(value => value + 1) };
}
