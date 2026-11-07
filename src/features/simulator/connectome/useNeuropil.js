import { useEffect, useState } from 'react';
import { loadNeuropil } from './neuropil';

export default function useNeuropil(runId, manifest, enabled) {
  const [state, setState] = useState({ meshes: [], loading: false, error: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ runId, manifest, enabled, meshes: [], loading: Boolean(runId && manifest && enabled), error: false });
    if (runId && manifest && enabled) loadNeuropil(runId, manifest, controller.signal, batch => {
      if (!controller.signal.aborted) setState(previous => !controller.signal.aborted && previous.runId === runId && previous.manifest === manifest && previous.enabled === enabled
        ? { ...previous, meshes: [...previous.meshes, ...batch] } : previous);
    }).then(() => {
      if (!controller.signal.aborted) setState(previous => !controller.signal.aborted && previous.runId === runId && previous.manifest === manifest && previous.enabled === enabled
        ? { ...previous, loading: false } : previous);
    }).catch(() => {
      if (!controller.signal.aborted) setState(previous => !controller.signal.aborted && previous.runId === runId && previous.manifest === manifest && previous.enabled === enabled
        ? { ...previous, loading: false, error: true } : previous);
    });
    return () => controller.abort();
  }, [runId, manifest, enabled, attempt]);
  const current = state.runId === runId && state.manifest === manifest && state.enabled === enabled;
  return { ...(current ? state : { meshes: [], loading: Boolean(runId && manifest && enabled), error: false }),
    retry: () => setAttempt(value => value + 1) };
}
