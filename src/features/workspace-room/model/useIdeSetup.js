import { useEffect, useRef, useState } from 'react';
import { provisionIdeRuntime, registerIdeRepository } from '@api/ide';
import { ideRepositoryPage, ideRuntime } from './ideReadContracts';
import { uploadIntentId } from './useWorkUploadSelection';

/** Explicit setup only. A lost registration ack reuses its exact immutable intent. */
export function useIdeSetup({ threadId, repositoryId, active, onCreated, onStarted }) {
  const scope = `${threadId || ''}:${repositoryId || ''}`;
  const [state, setState] = useState({ scope, busy: '', error: '', locked: false });
  const current = useRef({});
  current.current = { scope, active, onCreated, onStarted };
  const alive = useRef(false);
  const pending = useRef(null);
  const intent = useRef(null);
  const visit = useRef({ scope, active, id: 0 });
  if (visit.current.scope !== scope || visit.current.active !== active) {
    if (visit.current.scope !== scope) intent.current = null;
    visit.current = { scope, active, id: visit.current.id + 1 };
  }
  const visitId = visit.current.id;
  useEffect(() => { alive.current = true; return () => { alive.current = false; pending.current?.controller.abort(); }; }, []);
  useEffect(() => {
    pending.current?.controller.abort(); pending.current = null;
    // Leaving the surface retires its request, not a possibly committed create.
    // Only an explicit retry may send this same immutable intent again.
    setState({ scope, busy: '', error: intent.current ? 'create' : '', locked: Boolean(intent.current) });
    return () => { pending.current?.controller.abort(); pending.current = null; };
  }, [scope, active]);
  const run = async (kind, name) => {
    if (!threadId || !alive.current || visit.current.id !== visitId || !current.current.active || current.current.scope !== scope || pending.current) return false;
    const ticket = { controller: new AbortController() };
    pending.current = ticket;
    const owns = () => alive.current && visit.current.id === visitId && current.current.active && current.current.scope === scope && pending.current === ticket && !ticket.controller.signal.aborted;
    setState({ scope, busy: kind, error: '', locked: kind === 'create' });
    try {
      if (kind === 'create') {
        if (!intent.current) intent.current = { name, creation_intent_id: uploadIntentId(), create_thread_if_missing: true };
        const result = await registerIdeRepository(threadId, intent.current, ticket.controller.signal);
        ideRepositoryPage({ items: [result], next_offset: null }, 0);
        if (!owns()) return false;
        // Retire before acceptance changes the selected-repository scope.
        pending.current = null; intent.current = null;
        setState({ scope, busy: '', error: '', locked: false });
        current.current.onCreated(result);
      } else {
        const result = ideRuntime(await provisionIdeRuntime(threadId, repositoryId, ticket.controller.signal), repositoryId);
        if (!owns()) return false;
        setState({ scope, busy: '', error: result.state === 'unavailable' ? 'start_unavailable' : '', locked: false });
        current.current.onStarted();
      }
      return true;
    } catch {
      if (owns()) setState({ scope, busy: '', error: kind, locked: kind === 'create' && Boolean(intent.current) });
      return false;
    } finally { if (pending.current === ticket) pending.current = null; }
  };
  return { ...(state.scope === scope ? state : { busy: '', error: '', locked: false }),
    submittedName: state.scope === scope ? intent.current?.name || '' : '',
    create: (name) => run('create', name), start: () => run('start') };
}
