import { useEffect, useRef, useState } from 'react';
import { getIdeAgentCommands } from '@shared/api/ide';
import { useWorkActionOwner } from './useWorkActionOwner';

const pending = new Set(['preparing', 'ready', 'dispatching', 'running', 'stopping', 'unknown']);
const states = new Set([...pending, 'completed', 'failed', 'cancelled']);
const profiles = new Set(['shell', 'python_script', 'unittest', 'pytest']);

export function commandHistory(value, repositoryId, generation) {
  if (value?.repository_id !== repositoryId || value?.generation !== generation
    || !Array.isArray(value.entries) || value.entries.length > 30) throw Error('invalid_history');
  const ids = new Set();
  return value.entries.map(entry => {
    if (!entry || typeof entry.id !== 'string' || entry.id.length > 64 || ids.has(entry.id)
      || !states.has(entry.state) || !profiles.has(entry.profile)
      || (entry.target !== null && (typeof entry.target !== 'string' || entry.target.length > 1024))) throw Error('invalid_command');
    ids.add(entry.id);
    const result = entry.result;
    if (result && (!Number.isInteger(result.exit_code) || !Number.isFinite(result.duration_sec)
      || result.duration_sec < 0 || typeof result.stdout !== 'string' || result.stdout.length > 20000
      || typeof result.stderr !== 'string' || result.stderr.length > 20000
      || typeof result.truncated !== 'boolean' || typeof result.timed_out !== 'boolean')) throw Error('invalid_result');
    const verification = entry.verification?.status;
    if (verification && !['passed', 'failed', 'blocked', 'not_requested'].includes(verification)) throw Error('invalid_verification');
    return { id: `agent:${entry.id}`, source: 'agent', state: entry.state, result,
      command: `Агент · ${entry.profile === 'shell' ? 'Команда' : entry.profile === 'python_script' ? 'Python' : entry.profile}${entry.target ? ` · ${entry.target}` : ''}`,
      verification, blocker: entry.blocker, checkReason: entry.verification?.reason,
    };
  });
}

/** Read-only observation, fenced by repository/generation/visit; never replays. */
export function useIdeAgentCommands({ threadId, repositoryId, generation, active, available, watching, onChanged }) {
  const scope = `${threadId}/${repositoryId}/${generation}`;
  const [view, setView] = useState({ scope, entries: [], hidden: [], error: false });
  const [revision, refresh] = useState(0);
  const lifetime = useRef(0);
  const observed = useRef({ scope, states: new Map() });
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const owner = useWorkActionOwner({ threadId: scope, active });
  useEffect(() => {
    const visit = ++lifetime.current;
    if (!active || !available || !generation || !repositoryId || !threadId) return undefined;
    let retired = false; let timer;
    const controller = new AbortController();
    const expires = Date.now() + 180000;
    const read = async () => {
      try {
        const value = await getIdeAgentCommands(threadId, repositoryId, generation, controller.signal);
        const entries = commandHistory(value, repositoryId, generation);
        if (retired || visit !== lifetime.current) return;
        const finished = observed.current.scope === scope && entries.some(entry =>
          pending.has(observed.current.states.get(entry.id)) && !pending.has(entry.state));
        observed.current = { scope, states: new Map(entries.map(entry => [entry.id, entry.state])) };
        setView(current => ({ scope, entries, hidden: current.scope === scope ? current.hidden : [], error: false }));
        if (finished) { try { void Promise.resolve(changed.current?.()).catch(() => {}); } catch { /* Receipt remains confirmed. */ } }
        if ((watching || entries.some(entry => pending.has(entry.state))) && Date.now() < expires) timer = setTimeout(read, 2000);
      } catch {
        if (!retired && visit === lifetime.current) setView(current => ({
          scope, entries: current.scope === scope ? current.entries : [],
          hidden: current.scope === scope ? current.hidden : [], error: true,
        }));
      }
    };
    void read();
    return () => { retired = true; controller.abort(); clearTimeout(timer); };
  }, [scope, threadId, repositoryId, generation, active, available, watching, revision]);
  const current = view.scope === scope ? view : { entries: [], hidden: [], error: false };
  return {
    entries: current.entries.filter(entry => !current.hidden.includes(entry.id)),
    pending: current.entries.some(entry => pending.has(entry.state)), error: current.error,
    refresh: () => { if (owner.isCurrent(scope)) refresh(value => value + 1); },
    clear: () => setView(value => value.scope !== scope ? value : { ...value, hidden: value.entries.map(entry => entry.id) }),
  };
}
