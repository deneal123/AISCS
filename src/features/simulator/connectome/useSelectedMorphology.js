import { useEffect, useState } from 'react';
import { simulationApi } from '../api';
import { decodeSelectedMorphology } from './selectedMorphology';

export default function useSelectedMorphology(runId, nodeId, manifest) {
  const [state, setState] = useState({ data: null, loading: false, error: '' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ runId, nodeId, manifest, data: null, loading: Boolean(runId && nodeId && manifest), error: '' });
    if (runId && nodeId && manifest) simulationApi.morphology(runId, nodeId, controller.signal)
      .then(record => decodeSelectedMorphology(record, nodeId, manifest))
      .then(data => { if (!controller.signal.aborted) setState({ runId, nodeId, manifest, data, loading: false, error: '' }); })
      .catch(error => {
        if (!controller.signal.aborted) setState({ runId, nodeId, manifest, data: null, loading: false,
          error: (error?.status ?? error?.response?.status) === 404 ? 'Морфология этого нейрона ещё недоступна.' : 'Не удалось проверить морфологию нейрона.' });
      });
    return () => controller.abort();
  }, [runId, nodeId, manifest, attempt]);
  const current = state.runId === runId && state.nodeId === nodeId && state.manifest === manifest;
  return { ...(current ? state : { data: null, loading: Boolean(runId && nodeId && manifest), error: '' }),
    retry: () => setAttempt(value => value + 1) };
}
