import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkActionOwner } from './useWorkActionOwner';

const PENDING = new Set(['pending_audit', 'pending_delivery']);
const TERMINAL = new Set(['delivered', 'terminal']);
const OBSERVATION_WINDOW_MS = 300_000;
const STATUS_TIMEOUT_MS = 30_000;

export function waitDocumentStatus(signal, delay = 1000) {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return; }
    let timer;
    const done = () => {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', done);
      resolve();
    };
    timer = window.setTimeout(done, delay);
    signal.addEventListener('abort', done, { once: true });
  });
}

export function useDocumentPublication({
  threadId, build, setBuild, refreshSnapshot, notify, active = true, blocked = false,
}) {
  const buildId = build?.build_id;
  const artifactId = build?.artifacts?.find((item) => item.role === 'pdf')?.artifact_id;
  const scope = JSON.stringify([threadId, buildId, artifactId]);
  // Project snapshots originate in Workspace and cannot know the backend outbox.
  // Reconcile a recovered final build before offering a new publish mutation.
  const needsStatus = Boolean(build?.final && buildId && artifactId
    && !Object.hasOwn(build, 'publication_state'));
  const current = useRef(null);
  const monitor = useRef(null);
  const publication = useRef(null);
  const dispatchBlocked = useRef(null);
  const observationFailed = useRef(false);
  const [publicationError, setPublicationError] = useState(false);
  const [publicationChecking, setPublicationChecking] = useState(false);
  current.current = { scope, active, notify, refreshSnapshot,
    state: build?.publication_state, needsStatus };
  const { busy, begin, owns, finish } = useWorkActionOwner({
    threadId, active: active && !blocked,
  });

  const stopMonitoring = useCallback(() => {
    window.clearTimeout(monitor.current?.timer);
    monitor.current?.controller.abort();
    monitor.current = null;
  }, []);

  useEffect(() => {
    setPublicationError(false);
    dispatchBlocked.current = null;
    observationFailed.current = false;
  }, [scope]);

  useEffect(() => {
    setPublicationChecking(false);
    return () => {
      if (publication.current && current.current.scope === scope && !current.current.active) {
        setPublicationError(true);
      }
      stopMonitoring();
      finish(publication.current);
      publication.current = null;
    };
  }, [scope, active, finish, stopMonitoring]);

  const announce = useCallback((message) => {
    try { current.current.notify?.(message); } catch { /* Feedback cannot undo acknowledgement. */ }
  }, []);

  const refresh = useCallback(async () => {
    try { await current.current.refreshSnapshot?.({ background: true }); } catch {
      // Snapshot owns its partial failure. Never replay an acknowledged publication.
    }
  }, []);

  const checkPublication = useCallback(async () => {
    if (!threadId || !buildId || current.current.scope !== scope
      || !current.current.active || monitor.current) return null;
    const controller = new AbortController();
    const observation = { controller, timer: null };
    monitor.current = observation;
    const deadline = Date.now() + OBSERVATION_WINDOW_MS;
    const isCurrent = () => monitor.current === observation && !controller.signal.aborted
      && current.current.scope === scope && current.current.active;
    setPublicationError(false);
    observationFailed.current = false;
    setPublicationChecking(true);
    observation.timer = window.setTimeout(() => {
      if (!isCurrent()) return;
      observationFailed.current = true;
      setPublicationError(true);
      setPublicationChecking(false);
      // Abort the current read, not the durable server publication. Release UI
      // ownership now even if a transport responds late or ignores cancellation.
      controller.abort();
      monitor.current = null;
    }, OBSERVATION_WINDOW_MS);
    try {
      const { getDocumentBuild } = await import('@api/chat');
      for (let attempt = 0; attempt < 300 && isCurrent(); attempt += 1) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) break;
        const status = await getDocumentBuild(threadId, buildId, {
          signal: controller.signal, timeout: Math.min(STATUS_TIMEOUT_MS, remaining),
        });
        if (!isCurrent()) return null;
        if (status?.build_id !== buildId || !Object.hasOwn(status, 'publication_state')) {
          throw new Error('publication_protocol');
        }
        if (artifactId && !status.artifacts?.some((item) => (
          item?.role === 'pdf' && item.artifact_id === artifactId
        ))) throw new Error('publication_protocol');
        if (status.publication_state != null && !PENDING.has(status.publication_state)
          && !TERMINAL.has(status.publication_state)) throw new Error('publication_protocol');
        setBuild(status);
        if (TERMINAL.has(status.publication_state)) {
          if (status.publication_state === 'delivered') {
            announce({ title: 'Финальный PDF сохранён в Библиотеке', status: 'success' });
            void refresh();
          }
          return status;
        }
        // An authoritative read can prove that an uncertain POST created no job.
        // Stop here; only an explicit user action may enqueue a publication.
        if (status.publication_state == null) {
          dispatchBlocked.current = null;
          return status;
        }
        const pause = Math.min(1000, deadline - Date.now());
        if (pause <= 0) break;
        await waitDocumentStatus(controller.signal, pause);
      }
      if (isCurrent()) {
        observationFailed.current = true;
        setPublicationError(true);
      }
      return null;
    } catch {
      if (isCurrent()) {
        observationFailed.current = true;
        setPublicationError(true);
      }
      return null;
    } finally {
      window.clearTimeout(observation.timer);
      if (monitor.current === observation) {
        monitor.current = null;
        setPublicationChecking(false);
      }
    }
  }, [announce, artifactId, buildId, refresh, scope, setBuild, threadId]);

  useEffect(() => {
    if (active && !observationFailed.current
      && (needsStatus || PENDING.has(build?.publication_state))) void checkPublication();
  }, [active, build?.publication_state, checkPublication, needsStatus]);

  const publish = useCallback(async () => {
    if (!buildId || !artifactId || current.current.scope !== scope
      || current.current.needsStatus || dispatchBlocked.current === scope
      || monitor.current || PENDING.has(current.current.state)
      || TERMINAL.has(current.current.state)) return null;
    const ticket = begin(threadId, 'publish');
    if (!ticket) return null;
    publication.current = ticket;
    dispatchBlocked.current = scope;
    const isCurrent = () => owns(ticket) && current.current.scope === scope && current.current.active;
    setPublicationError(false);
    try {
      const { publishDocumentArtifact } = await import('@api/chat');
      if (!isCurrent()) return null;
      const result = await publishDocumentArtifact(threadId, buildId, artifactId);
      if (!isCurrent()) return null;
      const state = PENDING.has(result?.publication_state) || TERMINAL.has(result?.publication_state)
        ? result.publication_state
        : typeof result?.file_id === 'string' && result.file_id ? 'delivered' : null;
      if (state) {
        setBuild((previous) => previous?.build_id === buildId
          ? { ...previous, publication_state: state } : previous);
        if (state !== 'terminal') {
          announce({
            title: state === 'delivered' ? 'Финальный PDF уже в Библиотеке' : 'Сохранение поставлено в очередь',
            description: state === 'delivered' ? undefined : 'Проверка и доставка продолжатся в фоне.',
            status: state === 'delivered' ? 'success' : 'info', duration: 3400,
          });
        }
      } else {
        observationFailed.current = true;
        setPublicationError(true);
      }
      void refresh();
      if (state !== 'delivered' && state !== 'terminal') void checkPublication();
      return result;
    } catch {
      if (isCurrent()) {
        observationFailed.current = true;
        setPublicationError(true);
      }
      return null;
    } finally {
      if (publication.current === ticket) publication.current = null;
      finish(ticket);
    }
  }, [announce, artifactId, begin, buildId, checkPublication,
    finish, owns, refresh, scope, setBuild, threadId]);

  return {
    publish, checkPublication, publicationError, publicationChecking,
    publicationBusy: Boolean(busy),
  };
}
