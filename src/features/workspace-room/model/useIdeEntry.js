import { useCallback, useEffect, useRef, useState } from 'react';
import { prepareIdeWorkspace } from '@api/ide';
import { idePreparation } from './ideReadContracts';
import { getWorkspaceActorSession } from './workspaceSession';

/** First entry uses the server-owned identity and allocation claim, never a UI intent. */
export function useIdeEntry({ threadId, repositoryId, active, registryReady, blocked, onAccepted, onPrepared }) {
  const scope = `${threadId || ''}:${repositoryId || 'default'}`;
  const [session] = useState(getWorkspaceActorSession);
  const [state, setState] = useState({ scope, error: false });
  const current = useRef({});
  const pending = useRef(null);
  const alive = useRef(false);
  const completed = useRef({ threadId, items: new Map() });
  if (completed.current.threadId !== threadId) completed.current = { threadId, items: new Map() };
  const error = state.scope === scope && state.error;
  const eligible = Boolean(active && registryReady && threadId);
  current.current = { scope, eligible, blocked, error, onAccepted, onPrepared };
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; pending.current?.abort(); };
  }, []);
  const run = useCallback(async (continuation = false) => {
    if (!alive.current || current.current.scope !== scope || !current.current.eligible
      || current.current.blocked || pending.current) return;
    const controller = new AbortController(); pending.current = controller;
    const owns = () => alive.current && current.current.scope === scope && current.current.eligible
      && pending.current === controller && !controller.signal.aborted;
    setState({ scope, error: false, busy: true });
    try {
      const result = idePreparation(await prepareIdeWorkspace(threadId, repositoryId, controller.signal, session), repositoryId);
      if (!owns()) return;
      // Accepting the first descriptor changes scope. Record both identities
      // before acceptance so that it cannot trigger a second prepare request.
      for (const key of [scope, `${threadId}:${result.repository.repository_id}`]) {
        completed.current.items.set(key, { gitWarning: result.gitWarning,
          deferred: result.runtime.state !== 'ready', resumeAttempted: continuation });
      }
      while (completed.current.items.size > 64) completed.current.items.delete(completed.current.items.keys().next().value);
      pending.current = null;
      setState({ scope, error: false, busy: false });
      current.current.onAccepted(result.repository);
      current.current.onPrepared?.();
    } catch {
      if (owns()) setState({ scope, error: true, busy: false });
    } finally { if (pending.current === controller) pending.current = null; }
  }, [scope, threadId, repositoryId, session]);
  const resume = useCallback(() => {
    const report = completed.current.items.get(scope);
    if (!alive.current || !report?.deferred || report.resumeAttempted || pending.current || current.current.scope !== scope
      || !current.current.eligible || current.current.blocked) return;
    report.resumeAttempted = true;
    void run(true);
  }, [scope, run]);
  useEffect(() => {
    if (eligible && !blocked && !current.current.error && !completed.current.items.has(scope)) void run();
    return () => {
      const interrupted = pending.current;
      interrupted?.abort(); pending.current = null;
      if (!interrupted) return;
      // A retired request is not a completed continuation. Re-entering observes
      // the same repository before finishing setup; it must not stay busy forever.
      const report = completed.current.items.get(scope);
      if (report?.deferred) report.resumeAttempted = false;
      if (alive.current) setState(old => old.scope === scope ? { ...old, busy: false } : old);
    };
  }, [scope, eligible, blocked, run]);
  const report = completed.current.items.get(scope);
  return { waiting: eligible && !error && (!report || (state.scope === scope && state.busy)),
    awaitingReady: Boolean(report?.deferred && !report.resumeAttempted),
    error: eligible && error, gitWarning: Boolean(report?.gitWarning), retry: () => run(false), resume };
}
