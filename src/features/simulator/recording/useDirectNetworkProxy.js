import { useCallback, useEffect, useRef, useState } from 'react';
import { simulationApi } from '../api';
import { validFieldProgress } from './fieldProgress';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);

// A direct run has no physical electrode recording. Polling remains authoritative.
export default function useDirectNetworkProxy(onComplete, sceneId, canResume) {
  const [state, setState] = useState({ status: 'idle', run: null, progress: null });
  const callback = useRef(onComplete); callback.current = onComplete;
  const canResumeRef = useRef(canResume); canResumeRef.current = canResume;
  const abort = useRef(null);
  const selectedSimulation = useRef(null);
  const start = useCallback(async (targetSceneId, configuration) => {
    const controller = new AbortController(); abort.current = controller;
    setState({ status: 'loading', run: null, progress: null });
    const key = `simulation:direct:${targetSceneId}`;
    let request = configuration;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key));
      const comparable = value => JSON.stringify({ ...value, request_id: null });
      if (saved?.pending && comparable(saved.pending) === comparable(configuration)) request = saved.pending;
      sessionStorage.setItem(key, JSON.stringify({ pending: request }));
    } catch { /* An unavailable session store cannot provide reload recovery. */ }
    try {
      const run = await simulationApi.createFieldProxyDirect(targetSceneId, request, controller.signal);
      if (!controller.signal.aborted) {
        selectedSimulation.current = request.simulation;
        try { sessionStorage.setItem(key, JSON.stringify({ id: run.id, simulation: request.simulation })); } catch { /* Run continues without reload recovery. */ }
        // A retry may return an already completed run. Re-read it through the
        // same owner/scene-checked polling path before displaying its result.
        setState({ status: run.state === 'completed' ? 'queued' : run.state, run, progress: null });
      }
    } catch (error) {
      const status = error?.response?.status ?? error?.status;
      if (status >= 400 && status < 500 && status !== 429) {
        try { sessionStorage.removeItem(key); } catch { /* Storage is optional. */ }
      }
      if (!controller.signal.aborted) setState({ status: 'error', run: null, progress: null });
    }
  }, []);
  useEffect(() => {
    selectedSimulation.current = null;
    setState({ status: 'idle', run: null, progress: null });
    if (!sceneId) return undefined;
    try {
      const saved = JSON.parse(sessionStorage.getItem(`simulation:direct:${sceneId}`));
      // Do not resume an old submission when the operator has opened a fresh
      // experiment or edited its placement. A manual retry may still reuse it.
      if (canResumeRef.current && !canResumeRef.current()) return undefined;
      if (saved?.id && saved?.simulation) {
        selectedSimulation.current = saved.simulation;
        setState({ status: 'queued', run: { id: saved.id }, progress: null });
      } else if (saved?.pending?.request_id && saved?.pending?.simulation) {
        start(sceneId, saved.pending);
      }
    } catch { /* An invalid receipt cannot restore a run. */ }
    return () => abort.current?.abort();
  }, [sceneId, start]);
  const id = state.run?.id;
  useEffect(() => {
    if (!id || !active.has(state.status)) return undefined;
    const controller = new AbortController(); let timer, reconnect, socket, finished = false;
    async function poll() {
      try {
        const run = await simulationApi.get(id, controller.signal);
        if (controller.signal.aborted) return;
        if (run.parent_run_id !== sceneId) {
          setState({ status: 'error', run: null, progress: null }); return;
        }
        setState(previous => previous.run?.id === id ? { ...previous, status: run.state, run } : previous);
        if (active.has(run.state)) timer = setTimeout(poll, 3000);
        else {
          finished = true;
          if (run.state === 'completed') callback.current?.(run, selectedSimulation.current);
        }
      } catch {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      }
    }
    function connect() {
      if (controller.signal.aborted || finished) return;
      try {
        socket = new WebSocket(simulationApi.eventsUrl(id));
        socket.onopen = () => setState(previous => previous.run?.id === id
          ? { ...previous, connectionLost: false } : previous);
        socket.onmessage = message => {
          try {
            const event = JSON.parse(message.data), progress = event.event?.progress;
            if (event.event?.run_id === id && validFieldProgress(progress)) {
              setState(previous => previous.run?.id === id ? { ...previous, progress: { ...progress, runId: id } } : previous);
            }
          } catch { /* Polling remains authoritative. */ }
        };
        socket.onclose = () => {
          if (controller.signal.aborted || finished) return;
          setState(previous => previous.run?.id === id ? { ...previous, connectionLost: true } : previous);
          reconnect = setTimeout(connect, 2000);
        };
      } catch {
        setState(previous => previous.run?.id === id ? { ...previous, connectionLost: true } : previous);
        reconnect = setTimeout(connect, 2000);
      }
    }
    connect();
    poll();
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(reconnect); socket?.close(); };
  }, [id, state.status, sceneId]);
  const cancel = useCallback(async () => {
    if (state.run?.id && active.has(state.status)) await simulationApi.cancel(state.run.id);
    else abort.current?.abort();
  }, [state.run?.id, state.status]);
  return { ...state, start, cancel, running: state.status === 'loading' || active.has(state.status) };
}
