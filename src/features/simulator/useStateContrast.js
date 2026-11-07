import { useEffect, useState } from 'react';
import { simulationApi } from './api';
import { verifyStateContrast } from './stateContrast';
import { verifyFragmentTargetResponse } from './recording/fragmentTargetResponse';
import { verifyCoupledSparseDelta, verifyFragmentSparseDelta } from './recording/fragmentSparseDelta';

const fragmentResponsePresent = run => Array.isArray(run?.configuration?.source_ids)
  && run?.result?.manifest?.files?.some(file => file.name === 'fragment-response.bin');
const coupledResponsePresent = run => run?.result?.manifest?.kind === 'experimental-coupled-population'
  && run?.result?.manifest?.files?.some(file => file.name === 'coupled-delta.bin');

export default function useStateContrast(run, graph) {
  const [state, setState] = useState({ runId: null, graph: null, data: null, error: false, loading: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const fragment = fragmentResponsePresent(run);
    const coupled = coupledResponsePresent(run);
    const enabled = (run?.configuration?.retain_state_contrast === true || fragment || coupled) && Boolean(graph);
    setState({ runId: run?.id, graph, data: null, error: false, loading: enabled });
    if (enabled) (async () => {
      try {
        const files = (await simulationApi.artifacts(run.id, controller.signal)).items;
        const file = name => files.find(item => item.name === name);
        if (coupled) {
          const sparse = file('coupled-delta.bin');
          if (!sparse || sparse.bytes > 33000000) throw new Error('sparse_missing');
          const buffer = await simulationApi.readArtifact(run.id, sparse.id, controller.signal);
          const data = await verifyCoupledSparseDelta(buffer, sparse, run, graph);
          if (!controller.signal.aborted) setState({ runId: run.id, graph, data, error: false, loading: false });
          return;
        }
        if (fragment) {
          const sparse = file('fragment-delta.bin');
          if (sparse) {
            if (sparse.bytes > 33000000) throw new Error('sparse_oversized');
            const buffer = await simulationApi.readArtifact(run.id, sparse.id, controller.signal);
            const data = await verifyFragmentSparseDelta(buffer, sparse, run, graph);
            if (!controller.signal.aborted) setState({ runId: run.id, graph, data, error: false, loading: false });
            return;
          }
          const binary = file('fragment-response.bin');
          if (!binary || binary.bytes > 24000000) throw new Error('response_missing');
          const buffer = await simulationApi.readArtifact(run.id, binary.id, controller.signal);
          const data = await verifyFragmentTargetResponse(buffer, binary, run, graph);
          if (!controller.signal.aborted) setState({ runId: run.id, graph, data, error: false, loading: false });
          return;
        }
        const binary = file('state-contrast.bin'), description = file('state-contrast.json');
        const source = file('state-source-manifest.json'), graphFile = file('graph.bin'), metadata = file('metadata.json');
        if (!binary || !description || !source || !graphFile || !metadata || binary.bytes > 32000000
            || description.bytes > 16384 || source.bytes > 16384) throw new Error('state_missing');
        const [binaryBuffer, descriptionBuffer, sourceBuffer] = await Promise.all([binary, description, source]
          .map(item => simulationApi.readArtifact(run.id, item.id, controller.signal)));
        const data = await verifyStateContrast(binaryBuffer, binary, descriptionBuffer, description,
          sourceBuffer, source, graphFile, metadata, graph);
        if (!controller.signal.aborted) setState({ runId: run.id, graph, data, error: false, loading: false });
      } catch {
        if (!controller.signal.aborted) setState({ runId: run.id, graph, data: null, error: true, loading: false });
      }
    })();
    return () => controller.abort();
  }, [run, graph, attempt]);
  if (state.runId !== run?.id || state.graph !== graph) return { data: null, error: false, loading: Boolean(graph && (run?.configuration?.retain_state_contrast || fragmentResponsePresent(run) || coupledResponsePresent(run))) };
  return { ...state, retry: () => setAttempt(value => value + 1) };
}
