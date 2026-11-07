import { useEffect, useRef, useState } from 'react';
import { simulationApi } from '../api';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);

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

export default function useWholeNetworkProxy(source, enabled, createIfMissing) {
  const [state, setState] = useState({ sourceId: null, status: 'idle', run: null, progress: null });
  const localReceipt = useRef({ sourceId: null, requestId: null });
  useEffect(() => {
    if (!enabled || !source?.id || source.state !== 'completed') {
      setState({ sourceId: source?.id || null, status: 'idle', run: null, progress: null });
      return undefined;
    }
    const controller = new AbortController(), sourceId = source.id;
    let timer, reconnect, socket, watched = null, polling = false;
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
        setState(previous => ({ ...previous, sourceId, status: run.state, run, connectionLost: false }));
        if (active.has(run.state)) timer = setTimeout(() => poll().catch(fail), 4000);
        else { watched = null; socket?.close?.(); }
      } finally { polling = false; }
    }
    function connect(id) {
      if (controller.signal.aborted) return;
      try { socket = new WebSocket(simulationApi.eventsUrl(id)); } catch { return; }
      socket.onmessage = message => {
        try {
          const event = JSON.parse(message.data);
          const progress = event.event?.progress;
          if (event.event?.run_id === id && progress && ['field', 'field_verification', 'network'].includes(progress.phase)
              && Number.isInteger(progress.done) && Number.isInteger(progress.total)
              && ((progress.phase === 'field' && progress.total > 0 && progress.total <= 166700
                && progress.done >= 0 && progress.done <= progress.total)
                || (progress.phase !== 'field' && progress.done === 0 && progress.total === 0))) {
            setState(previous => previous.sourceId === sourceId ? { ...previous, progress } : previous);
          } else if (event.type === 'snapshot' || event.event?.run_id === id) poll().catch(fail);
        } catch { /* Polling remains authoritative. */ }
      };
      socket.onclose = () => { if (!controller.signal.aborted && watched === id) reconnect = setTimeout(() => connect(id), 2000); };
    }
    function fail(error) {
      if (controller.signal.aborted) return;
      if (['field_proxy_identity', 'field_proxy_result', 'field_proxy_list'].includes(error?.message)) {
        watched = null; socket?.close?.();
        setState({ sourceId, status: 'error', run: null, progress: null });
        return;
      }
      if (watched) {
        setState(previous => ({ ...previous, sourceId, connectionLost: true }));
        clearTimeout(timer);
        timer = setTimeout(() => poll().catch(fail), 2000);
      } else setState(previous => ({ ...previous, sourceId, status: 'error' }));
    }
    (async () => {
      const list = await simulationApi.fieldProxyRuns(sourceId, controller.signal);
      if (!Array.isArray(list?.items)) throw new Error('field_proxy_list');
      let run = list.items[0];
      if (!run && createIfMissing) {
        if (localReceipt.current.sourceId !== sourceId) {
          localReceipt.current = { sourceId, requestId: receipt(sourceId) };
        }
        run = await simulationApi.createFieldProxyFromFragment(sourceId, {
          request_id: localReceipt.current.requestId, gain: EXPERIMENTAL_FIELD_GAIN,
          allow_partial_geometry: true, allow_missing_curvature: true, allow_contact_exclusion: false,
        }, controller.signal);
      }
      if (controller.signal.aborted) return;
      if (!run?.id) { setState({ sourceId, status: 'unavailable', run: null, progress: null }); return; }
      watched = run.id; connect(run.id); await poll();
    })().catch(fail);
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(reconnect); socket?.close?.(); };
  }, [source?.id, source?.state, source?.configuration?.graph_manifest_sha256, enabled, createIfMissing]);
  return state.sourceId === source?.id ? state : { sourceId: source?.id || null, status: 'idle', run: null, progress: null };
}
