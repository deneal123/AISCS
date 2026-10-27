import { useEffect, useState } from 'react';
import { simulationApi } from './api';
import { verifyConnectome } from './connectomeData';

export default function useConnectomeData(runId, description) {
  const [result, setResult] = useState({ data: null, error: '', loading: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setResult({ data: null, error: '', loading: Boolean(runId && description) });
    if (runId && description) (async () => {
      try {
        const files = await simulationApi.artifacts(runId, controller.signal);
        const artifact = files.items.find(file => file.name === 'connectome.bin');
        if (!artifact) throw new Error('missing');
        const buffer = await simulationApi.readArtifact(runId, artifact.id, controller.signal);
        const data = await verifyConnectome(buffer, artifact, description);
        if (!controller.signal.aborted) setResult({ data, loading: false, error: '' });
      } catch {
        if (!controller.signal.aborted) setResult({ data: null, loading: false, error: 'Не удалось загрузить коннектом этого опыта. Запись и файлы остаются доступны.' });
      }
    })();
    return () => controller.abort();
  }, [runId, description, attempt]);
  return { ...result, retry: () => setAttempt(value => value + 1) };
}
