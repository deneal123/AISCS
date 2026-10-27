import { useEffect, useRef, useState } from 'react';
import { executeIdeCommand, getIdeCommand } from '@shared/api/ide';
import { useWorkActionOwner } from './useWorkActionOwner';
import { getWorkspaceActorSession } from './workspaceSession';
import { uploadIntentId } from './useWorkUploadSelection';
import { useIdeAgentCommands } from './useIdeAgentCommands';

function receipt(value, target, id) {
  if (!value || value.execution_id !== id || value.repository_id !== target.repositoryId
    || value.generation !== target.generation || !['dispatching', 'completed', 'unknown'].includes(value.state)) throw Error('invalid_receipt');
  const result = value.result;
  if (value.state === 'completed' && (!result || !Number.isInteger(result.exit_code)
    || typeof result.stdout !== 'string' || result.stdout.length > 20000
    || typeof result.stderr !== 'string' || result.stderr.length > 20000
    || typeof result.truncated !== 'boolean' || typeof result.timed_out !== 'boolean'
    || !Number.isFinite(result.duration_sec) || result.duration_sec < 0)) throw Error('invalid_result');
  return { state: value.state, result: value.state === 'completed' ? result : null };
}

/** Private memory-only command history. Reads reconcile; they never resubmit. */
export function useIdeConsole({ threadId, repositoryId, generation, active, available, blocked, watching, onChanged }) {
  const scope = `${threadId}/${repositoryId}/${generation}`;
  const [view, setView] = useState({ scope, draft: '', entries: [], error: '' });
  const owner = useWorkActionOwner({ threadId: scope, active });
  const agent = useIdeAgentCommands({ threadId, repositoryId, generation, active, available, watching, onChanged });
  const latest = useRef(null);
  latest.current = { threadId, repositoryId, generation, active, available, blocked, onChanged, scope, view, agentPending: agent.pending };
  useEffect(() => setView({ scope, draft: '', entries: [], error: '' }), [scope]);
  const visible = view.scope === scope ? view : { draft: '', entries: [], error: '' };
  const update = (id, value) => setView(current => current.scope !== scope ? current : {
    ...current, entries: current.entries.map(entry => entry.id === id ? { ...entry, ...value } : entry),
  });
  const accept = (id, value, target) => {
    const result = receipt(value, target, id);
    update(id, result);
    if (result.state === 'completed') {
      try { void Promise.resolve(latest.current.onChanged?.()).catch(() => {}); } catch { /* Output remains confirmed. */ }
    }
  };
  const run = async () => {
    const target = latest.current;
    const command = target.view.draft;
    if (!target.active || !target.available || target.blocked || target.agentPending || !command.trim()) return;
    if (command.length > 8192 || [...command].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) {
      setView(current => ({ ...current, error: 'Введите одну команду без управляющих символов, до 8192 знаков.' })); return;
    }
    const ticket = owner.begin(scope, 'run');
    if (!ticket) return;
    const id = uploadIntentId();
    setView(current => ({ ...current, error: '', entries: [...current.entries.slice(-29), { id, command, state: 'dispatching' }] }));
    try {
      const value = await executeIdeCommand(threadId, repositoryId, { execution_id: id, generation, command }, getWorkspaceActorSession());
      if (owner.owns(ticket)) accept(id, value, target);
    } catch { if (owner.owns(ticket)) update(id, { state: 'unknown', result: null }); }
    finally { owner.finish(ticket); }
  };
  const check = async (id) => {
    if (id.startsWith('agent:')) { agent.refresh(); return; }
    const target = latest.current;
    const ticket = owner.begin(scope, 'check');
    if (!ticket) return;
    try {
      const value = await getIdeCommand(threadId, repositoryId, id);
      if (owner.owns(ticket)) accept(id, value, target);
    } catch { if (owner.owns(ticket)) update(id, { state: 'unknown', result: null }); }
    finally { owner.finish(ticket); }
  };
  return { ...visible, entries: [...agent.entries, ...visible.entries],
    agentError: agent.error, checkAgent: agent.refresh, busy: owner.busy || (agent.pending ? 'agent' : ''), run, check,
    setDraft: draft => setView(current => ({ ...current, draft, error: '' })),
    clear: () => { if (!owner.busy) { agent.clear(); setView(current => ({ ...current, entries: [], error: '' })); } },
  };
}
