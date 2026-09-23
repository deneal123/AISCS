import { useCallback, useEffect, useRef, useState } from 'react';

const cancelled = (error) => error?.name === 'CanceledError'
  || error?.name === 'AbortError'
  || error?.code === 'ERR_CANCELED';

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
  threadRef.current = threadId;

  const load = useCallback(async () => {
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
      status: old.items.length ? old.status : 'loading',
    }));
    try {
      const { getWorkspaceIssues } = await import('@api/chat');
      const result = await getWorkspaceIssues(expectedThread, { signal: controller.signal });
      if (generation !== generationRef.current || threadRef.current !== expectedThread) return false;
      setState({ status: 'ready', items: [...(result?.issues || [])] });
      return true;
    } catch (error) {
      if (cancelled(error) || generation !== generationRef.current || threadRef.current !== expectedThread) {
        return false;
      }
      setState((old) => ({
        status: old.items.length ? 'stale' : 'unavailable',
        items: old.items,
      }));
      return false;
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [threadId, workspaceState]);

  useEffect(() => {
    generationRef.current += 1;
    controllerRef.current?.abort();
    setState({ status: 'idle', items: [] });
    load();
    return () => controllerRef.current?.abort();
  }, [load, threadId]);

  return {
    status: state.status,
    items: state.items,
    load,
  };
}

export default useWorkIssues;
