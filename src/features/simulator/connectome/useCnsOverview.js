import { useEffect, useState } from 'react';
import { loadOverview } from './cnsOverview';

export default function useCnsOverview(runId, manifest) {
  const [state, setState] = useState({ chunks: [], cells: 0, loading: false, error: '' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ runId, manifest, chunks: [], cells: 0, loading: Boolean(runId && manifest), error: '' });
    if (runId && manifest) loadOverview(runId, manifest, controller.signal, chunk => {
      if (!controller.signal.aborted) setState(previous => !controller.signal.aborted && previous.runId === runId && previous.manifest === manifest
        ? { ...previous, chunks: [...previous.chunks, chunk], cells: previous.cells + chunk.cells } : previous);
    }).then(() => {
      if (!controller.signal.aborted) setState(previous => !controller.signal.aborted && previous.runId === runId && previous.manifest === manifest
        ? { ...previous, loading: false } : previous);
    }).catch(() => {
      if (!controller.signal.aborted) setState(previous => !controller.signal.aborted && previous.runId === runId && previous.manifest === manifest
        ? { ...previous, loading: false, error: 'Не удалось проверить обзор отростков.' } : previous);
    });
    return () => controller.abort();
  }, [runId, manifest, attempt]);
  const current = state.runId === runId && state.manifest === manifest;
  return { ...(current ? state : { chunks: [], cells: 0, loading: Boolean(runId && manifest), error: '' }),
    retry: () => setAttempt(value => value + 1) };
}
