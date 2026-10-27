import { useCallback, useEffect, useRef, useState } from 'react';
import { getIdeCloneRecovery } from '@api/ide';
import { ideCloneRecovery } from './ideReadContracts';

const empty = scope => ({ scope, checked: false, loading: false, error: false, attempt: null, completed: false, observationExpired: false });

/** Discovery/polling is GET-only, independently of the explicit resume command. */
export function useIdeCloneRecovery({ threadId, repositoryId, active, onCompleted }) {
  const scope = `${threadId}:${repositoryId}`;
  const [state, setState] = useState(() => empty(scope));
  const pending = useRef(null);
  const alive = useRef(false);
  const observation = useRef({ scope, until: 0 });
  const current = useRef({}); current.current = { scope, active, onCompleted, state };
  const eligible = Boolean(active && threadId && repositoryId);
  useEffect(() => { alive.current = true; return () => { alive.current = false; pending.current?.abort(); }; }, []);
  const refresh = useCallback(async ({ observe = false } = {}) => {
    if (!alive.current || current.current.scope !== scope || !current.current.active || !threadId || !repositoryId) return;
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    if (!observe) observation.current = { scope, until: 0 };
    const valid = () => alive.current && current.current.scope === scope && current.current.active && pending.current === controller && !controller.signal.aborted;
    setState(old => ({ ...(old.scope === scope ? old : empty(scope)), loading: true, error: false, observationExpired: false }));
    try {
      const attempt = ideCloneRecovery(await getIdeCloneRecovery(threadId, repositoryId, controller.signal), repositoryId);
      if (!valid()) return;
      const previous = current.current.state.scope === scope ? current.current.state.attempt : null;
      const completed = previous?.intent_id === attempt?.intent_id && previous?.state !== 'complete' && attempt?.state === 'complete';
      setState(old => ({ scope, checked: true, loading: false, error: false, attempt,
        completed: Boolean(completed || (old.scope === scope && old.attempt?.intent_id === attempt?.intent_id && old.completed)),
        observationExpired: false }));
      if (completed) current.current.onCompleted?.(attempt);
    } catch {
      if (valid()) setState(old => ({ ...(old.scope === scope ? old : empty(scope)), loading: false, error: true, checked: true }));
    } finally { if (pending.current === controller) pending.current = null; }
  }, [scope, threadId, repositoryId]);
  useEffect(() => {
    if (eligible) void refresh();
    return () => { pending.current?.abort(); pending.current = null; };
  }, [eligible, refresh]);
  const visible = state.scope === scope ? state : empty(scope);
  useEffect(() => {
    if (!eligible || visible.attempt?.state !== 'running' || visible.loading || visible.error) return;
    if (observation.current.scope !== scope || !observation.current.until) observation.current = { scope, until: Date.now() + 90000 };
    if (Date.now() >= observation.current.until) {
      setState(old => old.observationExpired ? old : { ...old, observationExpired: true }); return;
    }
    const timer = setTimeout(() => { void refresh({ observe: true }); }, Math.min(1500, observation.current.until - Date.now()));
    return () => clearTimeout(timer);
  }, [eligible, scope, visible.attempt?.state, visible.loading, visible.error, refresh]);
  return { ...visible, loading: eligible && (!visible.checked || visible.loading), refresh };
}
