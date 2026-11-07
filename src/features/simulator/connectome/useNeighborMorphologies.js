import { useEffect, useState } from 'react';
import { simulationApi } from '../api';
import { decodeSelectedMorphology } from './selectedMorphology';

// Load only the displayed page in small batches. Apply results in page order so
// timing cannot change which cells fit the scene budget.
const MAX_VERTICES = 300000;
const BATCH_SIZE = 4;

export default function useNeighborMorphologies(runId, page, manifest) {
  const [state, setState] = useState({ data: null, loaded: 0, total: 0, unavailable: 0 });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const ids = [...new Set((page?.items || []).map(item => item.target_id || item.source_id).filter(Boolean))]
      .filter(id => id !== page?.nodeId);
    setState({ runId, page, manifest, data: null, loaded: 0, total: ids.length, unavailable: 0, omitted: 0, loading: Boolean(runId && manifest && ids.length) });
    if (!runId || !manifest || !ids.length) return () => controller.abort();
    (async () => {
      const arrays = [];
      let vertices = 0, unavailable = 0, omitted = 0;
      const publish = loading => {
        const size = arrays.reduce((sum, entry) => sum + entry.positions.length, 0);
        const positions = new Float32Array(size);
        let offset = 0; const ranges = [];
        arrays.forEach(({ id, positions: values }) => {
          positions.set(values, offset);
          ranges.push({ id, start: offset / 3, count: values.length / 3 });
          offset += values.length;
        });
        setState({ runId, page, manifest, data: { positions, vertices, ranges }, loaded: arrays.length,
          total: ids.length, unavailable, omitted, loading });
      };
      for (let start = 0; start < ids.length; start += BATCH_SIZE) {
        if (controller.signal.aborted) return;
        const batch = ids.slice(start, start + BATCH_SIZE);
        const results = await Promise.allSettled(batch.map(async id => {
          const raw = await simulationApi.morphology(runId, id, controller.signal);
          return decodeSelectedMorphology(raw, id, manifest);
        }));
        if (controller.signal.aborted) return;
        for (let index = 0; index < results.length; index += 1) {
          const result = results[index];
          if (result.status === 'rejected') { unavailable += 1; continue; }
          const cell = result.value;
          if (vertices + cell.vertices > MAX_VERTICES) omitted += 1;
          else { vertices += cell.vertices; arrays.push({ id: batch[index], positions: cell.positions }); }
        }
        publish(start + batch.length < ids.length);
      }
    })();
    return () => controller.abort();
  }, [runId, page, manifest, attempt]);
  const current = state.runId === runId && state.page === page && state.manifest === manifest;
  return { ...(current ? state : { data: null, loaded: 0, total: 0, unavailable: 0 }),
    retry: () => setAttempt(value => value + 1) };
}
