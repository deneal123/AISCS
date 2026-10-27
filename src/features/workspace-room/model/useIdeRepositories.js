import { useCallback, useEffect, useRef, useState } from 'react';
import { listIdeRepositories } from '@api/ide';
import { ideRepositoryPage } from './ideReadContracts';

const empty = (threadId) => ({ threadId, items: [], selectedId: '', status: 'idle', nextOffset: null, error: false, loading: false, failedOffset: 0 });

/** Private selection is memory-only; navigation never allocates or initializes Git. */
export function useIdeRepositories({ threadId, active, onThreadUnavailable }) {
  const [state, setState] = useState(() => empty(threadId));
  const current = useRef({});
  current.current = { threadId, active, onThreadUnavailable };
  const pending = useRef(null);
  const alive = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; pending.current?.abort(); };
  }, []);
  const load = useCallback(async (offset = 0) => {
    if (!threadId || !alive.current || !current.current.active || current.current.threadId !== threadId || (offset && pending.current)) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const owns = () => alive.current && current.current.active && current.current.threadId === threadId
      && pending.current === controller && !controller.signal.aborted;
    setState((old) => ({ ...(old.threadId === threadId ? old : empty(threadId)),
      status: old.threadId === threadId && old.status === 'ready' ? 'ready' : 'loading', loading: true, error: false }));
    try {
      const result = ideRepositoryPage(await listIdeRepositories(threadId, offset, controller.signal), offset);
      if (!owns()) return;
      setState((old) => {
        // Registry descriptors are append-only. A first-page refresh must not
        // evict the user's selected descriptor from a previously loaded page.
        const previous = old.threadId === threadId ? old.items : [];
        const items = [...new Map([...(offset ? previous : result.items), ...(offset ? result.items : previous)].map((item) => [item.repository_id, item])).values()];
        const selectedId = items.some((item) => item.repository_id === old.selectedId) ? old.selectedId : items[0]?.repository_id || '';
        return { threadId, items, selectedId, status: 'ready', nextOffset: result.nextOffset, loading: false, error: false, failedOffset: 0 };
      });
    } catch (error) {
      if (owns()) {
        setState((old) => ({ ...old, status: old.status === 'ready' ? 'ready' : 'error', loading: false, error: true, failedOffset: offset }));
        if (Number(error?.status || error?.response?.status) === 404) current.current.onThreadUnavailable?.(threadId);
      }
    } finally { if (pending.current === controller) pending.current = null; }
  }, [threadId]);
  useEffect(() => {
    if (active && threadId) void load();
    else { pending.current?.abort(); pending.current = null; setState((old) => ({ ...old, loading: false })); }
    return () => { pending.current?.abort(); pending.current = null; };
  }, [active, threadId, load]);
  const visible = state.threadId === threadId ? state : empty(threadId);
  const select = (repositoryId) => {
    if (!current.current.active || current.current.threadId !== threadId || !visible.items.some((item) => item.repository_id === repositoryId)) return;
    setState((old) => ({ ...old, selectedId: repositoryId }));
  };
  const accept = (descriptor) => {
    if (!alive.current || !current.current.active || current.current.threadId !== threadId) return false;
    const item = ideRepositoryPage({ items: [descriptor], next_offset: null }, 0).items[0];
    pending.current?.abort(); pending.current = null;
    setState((old) => ({ ...(old.threadId === threadId ? old : empty(threadId)),
      items: [item, ...(old.threadId === threadId ? old.items.filter((entry) => entry.repository_id !== item.repository_id) : [])],
      selectedId: item.repository_id, status: 'ready', error: false, loading: false }));
    return true;
  };
  return { ...visible, load, select, accept, selected: visible.items.find((item) => item.repository_id === visible.selectedId) || null };
}
