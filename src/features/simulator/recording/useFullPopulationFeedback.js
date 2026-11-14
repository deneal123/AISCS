import { useCallback, useEffect, useRef, useState } from 'react';
import { simulationApi } from '../api';
import { validFullProgress } from './fieldProgress';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);

// Polling is authoritative; websocket messages only trigger a fresh read.
export default function useFullPopulationFeedback(onComplete, sceneId, resumeContext) {
  const [state, setState] = useState({ status: 'idle', run: null });
  const callback = useRef(onComplete); callback.current = onComplete;
  const resume = useRef(resumeContext); resume.current = resumeContext;
  const abort = useRef(null);
  const cancelPending = useRef(false);
  const pendingResume = useRef(null);
  const start = useCallback(async (configuration, context, restoredRequest = null) => {
    abort.current?.abort();
    cancelPending.current = false;
    pendingResume.current = null;
    const controller = new AbortController(); abort.current = controller;
    setState({ status: 'loading', run: null });
    const request = restoredRequest || { request_id: crypto.randomUUID(),
      title: 'Связанный расчёт ЦНС', configuration };
    const receipt = { version: 1, signature: context?.signature,
      graph: configuration.graph_manifest_sha256 };
    if (sceneId && context?.signature) {
      try { sessionStorage.setItem(`simulation:full:${sceneId}`, JSON.stringify({
        ...receipt, pending: request,
      })); } catch { /* Retry recovery is unavailable without storage. */ }
    }
    try {
      const run = await simulationApi.createFullFeedback(request, controller.signal);
      if (!controller.signal.aborted) {
        if (sceneId && context?.signature && run?.id) {
          try { sessionStorage.setItem(`simulation:full:${sceneId}`, JSON.stringify({
            ...receipt, id: run.id,
          })); } catch { /* The active run remains available without storage. */ }
        }
        if (restoredRequest) pendingResume.current = receipt;
        if (cancelPending.current && run?.id) {
          try {
            await simulationApi.cancel(run.id);
            setState({ status: 'cancelled', run });
          } catch { setState({ status: 'queued', run }); }
        } else setState({ status: 'queued', run });
      }
    } catch (error) {
      const status = error?.response?.status ?? error?.status;
      if (sceneId && status >= 400 && status < 500 && status !== 429) {
        try {
          const key = `simulation:full:${sceneId}`;
          if (JSON.parse(sessionStorage.getItem(key))?.pending?.request_id === request.request_id)
            sessionStorage.removeItem(key);
        } catch { /* Storage is optional. */ }
      }
      if (!controller.signal.aborted) setState({ status: 'error', run: null });
    }
  }, [sceneId]);
  useEffect(() => {
    abort.current?.abort();
    cancelPending.current = false;
    pendingResume.current = null;
    setState({ status: 'idle', run: null });
    if (!sceneId) return undefined;
    try {
      const receipt = JSON.parse(sessionStorage.getItem(`simulation:full:${sceneId}`));
      if (receipt?.version === 1 && typeof receipt.id === 'string'
          && typeof receipt.signature === 'string' && typeof receipt.graph === 'string'
          && resume.current?.canResume?.(receipt)) {
        pendingResume.current = receipt;
        setState({ status: 'queued', run: { id: receipt.id } });
      } else if (receipt?.version === 1 && typeof receipt.signature === 'string'
          && typeof receipt.graph === 'string' && typeof receipt.pending?.request_id === 'string'
          && receipt.pending?.configuration?.graph_manifest_sha256 === receipt.graph
          && resume.current?.canResume?.(receipt)) {
        start(receipt.pending.configuration, { signature: receipt.signature }, receipt.pending);
      }
    } catch { /* A damaged receipt cannot restore an experience. */ }
    return undefined;
  }, [sceneId, start]);
  const id = state.run?.id;
  useEffect(() => {
    if (!id || !active.has(state.status)) return undefined;
    const controller = new AbortController(); let timer, reconnect, socket, done = false, polling = false;
    async function poll() {
      if (polling || done) return;
      polling = true;
      try {
        const run = await simulationApi.get(id, controller.signal);
        if (controller.signal.aborted) return;
        if (!run || run.id !== id) { done = true; setState({ status: 'error', run: null }); return; }
        if (pendingResume.current) {
          const receipt = pendingResume.current;
          pendingResume.current = null;
          if (!resume.current?.validateResume?.(receipt, run)) {
            done = true; setState({ status: 'error', run: null }); return;
          }
          resume.current.onResume?.(receipt, run);
        }
        setState(previous => previous.run?.id === id ? { ...previous, status: run.state, run } : previous);
        if (active.has(run.state)) timer = setTimeout(poll, 3000);
        else {
          done = true;
          if (sceneId) {
            try {
              const key = `simulation:full:${sceneId}`;
              if (JSON.parse(sessionStorage.getItem(key))?.id === id) sessionStorage.removeItem(key);
            } catch { /* Storage is optional. */ }
          }
          if (run.state === 'completed'
              && run.result?.manifest?.kind === 'experimental-full-population-feedback'
              && run.result?.preview?.status === 'converged') callback.current?.(run);
        }
      } catch {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      } finally { polling = false; }
    }
    function connect() {
      if (controller.signal.aborted || done) return;
      try {
        socket = new WebSocket(simulationApi.eventsUrl(id));
        socket.onopen = () => setState(previous => previous.run?.id === id
          ? { ...previous, connectionLost: false } : previous);
        socket.onmessage = message => {
          try {
            const event = JSON.parse(message.data);
            if (event.event?.run_id === id && validFullProgress(event.event.progress)) {
              setState(previous => previous.run?.id === id ? { ...previous,
                progress: { ...event.event.progress, runId: id } } : previous);
            }
            if (event.event?.run_id === id || event.run?.id === id) { clearTimeout(timer); poll(); }
          } catch { /* The next poll remains authoritative. */ }
        };
        socket.onclose = () => {
          if (controller.signal.aborted || done) return;
          setState(previous => previous.run?.id === id
            ? { ...previous, connectionLost: true } : previous);
          reconnect = setTimeout(connect, 2000);
        };
      } catch {
        setState(previous => previous.run?.id === id
          ? { ...previous, connectionLost: true } : previous);
        reconnect = setTimeout(connect, 2000);
      }
    }
    connect(); poll();
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(reconnect); socket?.close(); };
  }, [id, state.status, sceneId]);
  useEffect(() => () => abort.current?.abort(), []);
  const cancel = useCallback(async () => {
    if (state.run?.id && active.has(state.status)) await simulationApi.cancel(state.run.id);
    else cancelPending.current = true;
  }, [state.run?.id, state.status]);
  return { ...state, start, cancel, running: state.status === 'loading' || active.has(state.status) };
}
