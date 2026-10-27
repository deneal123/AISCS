import { useCallback, useEffect, useRef, useState } from 'react';

const cancelled = (error) => error?.name === 'CanceledError'
  || error?.name === 'AbortError'
  || error?.code === 'ERR_CANCELED';

const hasSnapshot = (state) => state.status === 'ready' || state.status === 'stale';

/**
 * Loads issue content through its protected endpoint. Work snapshot carries
 * only aggregate room state, so an issue failure must never downgrade the
 * workspace or erase the last successfully loaded issue list.
 */
export function useWorkIssues({ threadId, workspaceState }) {
  const [state, setState] = useState({ status: 'idle', items: [] });
  const generationRef = useRef(0);
  const threadRef = useRef(threadId);
  const controllerRef = useRef(null);
  const activeRef = useRef(false);
  const loadRef = useRef(null);
  threadRef.current = threadId;

  const load = useCallback(async function loadIssues() {
    // A completed mutation may retain this callback after navigation. Reject it
    // before it can abort a newer request or reset another context's content.
    if (!activeRef.current || loadRef.current !== loadIssues) return false;
    const expectedThread = threadId;
    if (!expectedThread || workspaceState !== 'ready') {
      controllerRef.current?.abort();
      setState({ status: 'idle', items: [] });
      return false;
    }

    const generation = ++generationRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((old) => ({
      ...old,
      status: hasSnapshot(old) ? old.status : 'loading',
    }));
    try {
      const { getWorkspaceIssues } = await import('@api/chat');
      if (controller.signal.aborted || !activeRef.current
        || loadRef.current !== loadIssues) return false;
      const result = await getWorkspaceIssues(expectedThread, { signal: controller.signal });
      if (controller.signal.aborted || generation !== generationRef.current
        || threadRef.current !== expectedThread) return false;
      setState({ status: 'ready', items: [...(result?.issues || [])] });
      return true;
    } catch (error) {
      if (controller.signal.aborted || cancelled(error)
        || generation !== generationRef.current || threadRef.current !== expectedThread) {
        return false;
      }
      setState((old) => ({
        status: hasSnapshot(old) ? 'stale' : 'unavailable',
        items: old.items,
      }));
      return false;
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [threadId, workspaceState]);
  loadRef.current = load;

  useEffect(() => {
    activeRef.current = true;
    generationRef.current += 1;
    controllerRef.current?.abort();
    setState({ status: 'idle', items: [] });
    load();
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [load, threadId]);

  return {
    status: state.status,
    items: state.items,
    load,
  };
}

export default useWorkIssues;
