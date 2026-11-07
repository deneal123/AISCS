import { useEffect, useState } from 'react';
import { simulationApi } from '../api';
import { decodeSelectedMorphology } from '../connectome/selectedMorphology';

// Load sequentially to avoid requesting every large SWC simultaneously.
// Missing cells stay visible as an explicit list, never as invented geometry.
export default function useFieldMorphologies(runId, ids, manifest) {
  const key = JSON.stringify(ids);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ key: '', data: [], missing: [], loading: false });
  useEffect(() => {
    const controller = new AbortController();
    const cells = JSON.parse(key), data = [], missing = [];
    setState({ runId, manifest, key, data: [], missing: [], loading: Boolean(runId && manifest && cells.length) });
    async function load() {
      for (const id of cells) {
        try {
          const record = await simulationApi.morphology(runId, id, controller.signal);
          const decoded = await decodeSelectedMorphology(record, id, manifest);
          if (controller.signal.aborted) return;
          data.push({ id, ...decoded });
        } catch {
          if (controller.signal.aborted) return;
          missing.push(id);
        }
      }
      if (!controller.signal.aborted) setState({ runId, manifest, key, data, missing, loading: false });
    }
    if (runId && manifest && cells.length) load();
    return () => controller.abort();
  }, [runId, manifest, key, attempt]);
  const current = state.runId === runId && state.manifest === manifest && state.key === key;
  return { ...(current ? state : { data: [], missing: [], loading: Boolean(runId && manifest && ids.length) }),
    retry: () => setAttempt(value => value + 1) };
}
