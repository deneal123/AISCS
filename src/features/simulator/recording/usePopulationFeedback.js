import { useEffect, useRef, useState } from 'react';
import { simulationApi } from '../api';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const synapse = { weight_us: .001, tau1_ms: .2, tau2_ms: 2, reversal_mv: 0 };

function displayable(run, source) {
  const preview = run?.result?.preview, timeline = preview?.timeline;
  const files = run?.result?.manifest?.files;
  return run?.parent_run_id === source.id
    && run.configuration?.graph_manifest_sha256 === source.configuration?.graph_manifest_sha256
    && ['converged', 'converged_partial'].includes(preview?.status)
    && Array.isArray(timeline?.time_ms) && timeline.time_ms.length >= 2
    && Array.isArray(timeline?.neural_uv) && timeline.neural_uv.length === timeline.time_ms.length
    && Array.isArray(files) && ['coupled-events.bin', 'coupled-delta.bin'].every(name =>
      files.some(file => file.name === name));
}

// The initial physical population and its feedback stage form one user action.
// Explicit, uncalibrated constants are retained in the submitted configuration.
export default function usePopulationFeedback(source, autoCreate, requestId = null, retryReceipt = false, onRetryRequest = null) {
  const [state, setState] = useState({ sourceId: null, status: 'idle', run: null });
  const [feedbackProgress, setFeedbackProgress] = useState(null);
  const [retryRevision, setRetryRevision] = useState(0);
  const pending = useRef({ sourceId: null, requestId: null });
  const retryPending = useRef(null);
  const onRetryRequestRef = useRef(onRetryRequest); onRetryRequestRef.current = onRetryRequest;
  const currentSource = useRef(source?.id); currentSource.current = source?.id;
  useEffect(() => {
    if (!source?.id || source.state !== 'completed') {
      setState({ sourceId: source?.id || null, status: 'idle', run: null });
      return undefined;
    }
    const controller = new AbortController();
    let timer, reconnectTimer, socket, polling = false, watchedId = null, lastSnapshot = null;
    const sourceId = source.id;
    setFeedbackProgress(null);
    setState({ sourceId, status: 'loading', run: null });
    let previousCompletedId = null;
    async function poll(id) {
      if (polling || controller.signal.aborted) return;
      polling = true; clearTimeout(timer);
      try {
        const run = await simulationApi.get(id, controller.signal);
        if (controller.signal.aborted) return;
        if (run.state === 'completed' && !displayable(run, source)) {
          setState({ sourceId, status: 'unavailable', run: null }); return;
        }
        setState({ sourceId, status: run.state, run, previousCompletedId, connectionLost: false });
        if (active.has(run.state)) timer = setTimeout(() => poll(id).catch(fail), 4000);
        else { watchedId = null; socket?.close?.(); }
      } finally { polling = false; }
    }
    function connect(id) {
      if (controller.signal.aborted) return;
      try { socket = new WebSocket(simulationApi.eventsUrl(id)); } catch { return; }
      socket.onmessage = message => {
        try {
          const payload = JSON.parse(message.data);
          if (payload.type === 'snapshot' && payload.run?.id === id) {
            const version = payload.run.state;
            if (version !== lastSnapshot) { lastSnapshot = version; poll(id).catch(fail); }
          } else if (payload.event?.run_id === id) {
            const progress = payload.event.progress;
            if (progress && ['feedback_network', 'feedback_cells'].includes(progress.phase)
                && Number.isInteger(progress.iteration) && progress.iteration >= 1 && progress.iteration <= 100
                && Number.isInteger(progress.done) && Number.isInteger(progress.total)
                && ((progress.phase === 'feedback_network' && progress.done === 0 && progress.total === 0)
                  || (progress.phase === 'feedback_cells' && progress.done > 0
                      && progress.done <= progress.total && progress.total <= 256))) {
              setFeedbackProgress({ ...progress, sourceId, runId: id });
            } else poll(id).catch(fail);
          }
        } catch { /* HTTP reconciliation remains authoritative. */ }
      };
      socket.onclose = () => {
        if (!controller.signal.aborted && watchedId === id) reconnectTimer = setTimeout(() => connect(id), 2000);
      };
    }
    function fail() {
      if (controller.signal.aborted) return;
      if (watchedId) {
        setState(previous => previous.sourceId === sourceId && previous.run
          ? { ...previous, connectionLost: true } : { sourceId, status: 'loading', run: null, connectionLost: true });
        clearTimeout(timer);
        timer = setTimeout(() => poll(watchedId).catch(fail), 2000);
      } else setState({ sourceId, status: 'error', run: null });
    }
    (async () => {
      const list = await simulationApi.feedbackRuns(sourceId, controller.signal);
      if (!Array.isArray(list?.items)) throw new Error('invalid_feedback_list');
      let run = list.items[0];
      previousCompletedId = list.items.find(item => item.id !== run?.id && item.state === 'completed')?.id || null;
      const retry = retryPending.current?.sourceId === sourceId ? retryPending.current : null;
      if ((!run && autoCreate) || (retry && !active.has(run?.state)) || (autoCreate && retryReceipt)) {
        const receipt = await simulationApi.feedbackSource(sourceId, controller.signal);
        if (controller.signal.aborted) return;
        if (receipt.graph_manifest_sha256 !== source.configuration?.graph_manifest_sha256
            || !/^[a-f0-9]{64}$/.test(receipt.sha256 || '')
            || !/^[a-f0-9]{64}$/.test(receipt.manifest_sha256 || '')) throw new Error('source_identity');
        const chosenId = retry?.requestId || requestId;
        if (pending.current.sourceId !== sourceId || (chosenId && pending.current.requestId !== chosenId)) {
          pending.current = { sourceId, requestId: chosenId || crypto.randomUUID() };
        }
        run = await simulationApi.createFeedback({ request_id: pending.current.requestId,
          parent_run_id: sourceId, title: 'Связанный расчёт ЦНС', configuration: {
            graph_manifest_sha256: receipt.graph_manifest_sha256,
            source_package_sha256: receipt.sha256, source_manifest_sha256: receipt.manifest_sha256,
            excitatory: synapse, inhibitory: { ...synapse, reversal_mv: -80 },
            max_iterations: 16, allow_partial_geometry: true,
          } }, controller.signal);
        if (retryPending.current === retry) retryPending.current = null;
      }
      if (controller.signal.aborted) return;
      if (!run?.id) { setState({ sourceId, status: 'unavailable', run: null }); return; }
      watchedId = run.id; connect(run.id);
      await poll(run.id);
    })().catch(fail);
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(reconnectTimer); socket?.close?.(); };
  }, [source, autoCreate, requestId, retryReceipt, retryRevision]);
  if (!source?.id) return { sourceId: null, status: 'idle', run: null };
  const current = state.sourceId === source.id ? state : { sourceId: source.id, status: 'loading', run: null };
  async function restorePrevious() {
    if (!current.previousCompletedId || currentSource.current !== source.id) return;
    try {
      const run = await simulationApi.get(current.previousCompletedId);
      if (currentSource.current !== source.id) return;
      if (run.state !== 'completed' || !displayable(run, source)) throw new Error('invalid_previous_result');
      setState({ sourceId: source.id, status: 'completed', run, previousCompletedId: null });
    } catch {
      if (currentSource.current === source.id) setState({ sourceId: source.id, status: 'error', run: null });
    }
  }
  function retry() {
    if (!source?.id || !['failed', 'cancelled', 'error', 'unavailable'].includes(current.status)) return;
    if (retryPending.current?.sourceId !== source.id) {
      retryPending.current = { sourceId: source.id, requestId: crypto.randomUUID() };
    }
    onRetryRequestRef.current?.(retryPending.current);
    setState({ sourceId: source.id, status: 'loading', run: null });
    setRetryRevision(value => value + 1);
  }
  return { ...current, progress: feedbackProgress?.sourceId === source.id
    && feedbackProgress?.runId === current.run?.id ? feedbackProgress : null, restorePrevious, retry };
}
