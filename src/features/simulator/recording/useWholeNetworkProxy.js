import { useEffect, useRef, useState } from 'react';
import { simulationApi } from '../api';
import { validFieldProgress } from './fieldProgress';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// Explicit engineering value, not a physiological calibration.
export const EXPERIMENTAL_FIELD_GAIN = 1000000;

function receipt(sourceId) {
  const key = `simulation:field-proxy-request:${sourceId}`;
  try {
    const previous = sessionStorage.getItem(key);
    if (previous) return previous;
    const id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

function retryReceipt(sourceId, graph) {
  try {
    const item = JSON.parse(sessionStorage.getItem(`simulation:field-proxy-retry:${sourceId}`));
    return item?.graph === graph && typeof item.requestId === 'string' && uuid.test(item.requestId)
      ? item.requestId : null;
  } catch { return null; }
}

function rememberRetry(sourceId, graph, requestId) {
  try { sessionStorage.setItem(`simulation:field-proxy-retry:${sourceId}`, JSON.stringify({ graph, requestId })); }
  catch { /* The current component still retains the request ID. */ }
}

function clearRetry(sourceId, graph, requestId) {
  try {
    if (retryReceipt(sourceId, graph) === requestId) sessionStorage.removeItem(`simulation:field-proxy-retry:${sourceId}`);
  } catch { /* Storage is optional. */ }
}

export default function useWholeNetworkProxy(source, enabled, createIfMissing) {
  const [state, setState] = useState({ sourceId: null, status: 'idle', run: null, progress: null });
  const [retryRevision, setRetryRevision] = useState(0);
  const localReceipt = useRef({ sourceId: null, requestId: null });
  const retryPending = useRef(null);
  useEffect(() => {
    if (!enabled || !source?.id || source.state !== 'completed') {
      setState({ sourceId: source?.id || null, status: 'idle', run: null, progress: null });
      return undefined;
    }
    const controller = new AbortController(), sourceId = source.id;
    let timer, reconnect, socket, watched = null, polling = false;
    let socketOpen = false, pollFailed = false;
    setState({ sourceId, status: 'loading', run: null, progress: null });
    async function poll() {
      if (polling || controller.signal.aborted || !watched) return;
      clearTimeout(timer);
      polling = true;
      try {
        const run = await simulationApi.get(watched, controller.signal);
        if (controller.signal.aborted) return;
        if (run.parent_run_id !== sourceId
            || run.configuration?.graph_manifest_sha256 !== source.configuration?.graph_manifest_sha256)
          throw new Error('field_proxy_identity');
        if (run.state === 'completed' && (run.result?.manifest?.kind !== 'experimental-field-proxy'
            || run.result?.preview?.recording !== null)) throw new Error('field_proxy_result');
        pollFailed = false;
        setState(previous => ({ ...previous, sourceId, status: run.state, run, connectionLost: !socketOpen }));
        if (active.has(run.state)) timer = setTimeout(() => poll().catch(fail), 4000);
        else { watched = null; socket?.close?.(); }
      } finally { polling = false; }
    }
    function connect(id) {
      if (controller.signal.aborted || watched !== id) return;
      try { socket = new WebSocket(simulationApi.eventsUrl(id)); } catch {
        socketOpen = false;
        setState(previous => previous.sourceId === sourceId ? { ...previous, connectionLost: true } : previous);
        reconnect = setTimeout(() => connect(id), 2000);
        return;
      }
      const currentSocket = socket;
      currentSocket.onopen = () => {
        if (controller.signal.aborted || socket !== currentSocket || watched !== id) return;
        socketOpen = true;
        setState(previous => previous.sourceId === sourceId ? { ...previous, connectionLost: pollFailed } : previous);
      };
      currentSocket.onmessage = message => {
        if (controller.signal.aborted || socket !== currentSocket || watched !== id) return;
        try {
          const event = JSON.parse(message.data);
          const progress = event.event?.progress;
          if (event.event?.run_id === id && validFieldProgress(progress)) {
            setState(previous => previous.sourceId === sourceId ? { ...previous, progress: { ...progress, runId: id } } : previous);
          } else if (event.type === 'snapshot' || event.event?.run_id === id) poll().catch(fail);
        } catch { /* Polling remains authoritative. */ }
      };
      currentSocket.onclose = () => {
        if (controller.signal.aborted || socket !== currentSocket || watched !== id) return;
        socketOpen = false;
        setState(previous => previous.sourceId === sourceId ? { ...previous, connectionLost: true } : previous);
        reconnect = setTimeout(() => connect(id), 2000);
      };
    }
    function fail(error) {
      if (controller.signal.aborted) return;
      if (['field_proxy_identity', 'field_proxy_result', 'field_proxy_list'].includes(error?.message)) {
        watched = null; socket?.close?.();
        setState({ sourceId, status: 'error', run: null, progress: null });
        return;
      }
      if (watched) {
        pollFailed = true;
        setState(previous => ({ ...previous, sourceId, connectionLost: true }));
        clearTimeout(timer);
        timer = setTimeout(() => poll().catch(fail), 2000);
      } else setState(previous => ({ ...previous, sourceId, status: 'error' }));
    }
    (async () => {
      const list = await simulationApi.fieldProxyRuns(sourceId, controller.signal);
      if (!Array.isArray(list?.items)) throw new Error('field_proxy_list');
      let run = list.items[0];
      const graph = source.configuration?.graph_manifest_sha256;
      const retryId = retryPending.current?.sourceId === sourceId && retryPending.current?.graph === graph
        ? retryPending.current.requestId : retryReceipt(sourceId, graph);
      if ((!run && createIfMissing) || retryId) {
        if (!retryId && localReceipt.current.sourceId !== sourceId) {
          localReceipt.current = { sourceId, requestId: receipt(sourceId) };
        }
        const requestId = retryId || localReceipt.current.requestId;
        try {
          run = await simulationApi.createFieldProxyFromFragment(sourceId, {
            request_id: requestId, gain: EXPERIMENTAL_FIELD_GAIN,
            allow_partial_geometry: true, allow_missing_curvature: true, allow_contact_exclusion: false,
          }, controller.signal);
        } catch (error) {
          const status = error?.response?.status ?? error?.status;
          if (retryId && status >= 400 && status < 500 && status !== 429) {
            clearRetry(sourceId, graph, retryId);
            if (retryPending.current?.requestId === retryId) retryPending.current = null;
          }
          throw error;
        }
        if (controller.signal.aborted) return;
        if (retryId && run?.id) {
          clearRetry(sourceId, graph, retryId);
          if (retryPending.current?.requestId === retryId) retryPending.current = null;
        }
      }
      if (controller.signal.aborted) return;
      if (!run?.id) { setState({ sourceId, status: 'unavailable', run: null, progress: null }); return; }
      watched = run.id; connect(run.id); await poll();
    })().catch(fail);
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(reconnect); socket?.close?.(); };
  }, [source?.id, source?.state, source?.configuration?.graph_manifest_sha256, enabled, createIfMissing, retryRevision]);
  const current = state.sourceId === source?.id ? state : { sourceId: source?.id || null, status: 'idle', run: null, progress: null };
  function retry() {
    if (!enabled || source?.state !== 'completed' || !['failed', 'error', 'unavailable', 'cancelled'].includes(current.status)) return;
    const graph = source.configuration?.graph_manifest_sha256;
    if (!source.id || typeof graph !== 'string' || !graph) return;
    const requestId = retryPending.current?.sourceId === source.id && retryPending.current?.graph === graph
      ? retryPending.current.requestId : retryReceipt(source.id, graph) || crypto.randomUUID();
    retryPending.current = { sourceId: source.id, graph, requestId };
    rememberRetry(source.id, graph, requestId);
    setState({ sourceId: source.id, status: 'loading', run: null, progress: null });
    setRetryRevision(value => value + 1);
  }
  return { ...current, retry };
}
