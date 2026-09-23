import { useCallback, useEffect, useRef, useState } from 'react';
import { EMPTY_WORK_HUB } from './constants';

const emptyWorkspace = (state = 'absent') => ({
  ...EMPTY_WORK_HUB.workspace,
  state,
  entries: [],
  history: [],
});

const emptyRoom = (state = 'absent') => ({
  ...EMPTY_WORK_HUB.room,
  state,
  issues: [],
  activity: [],
  leases: [],
});

const statusOf = (error) => Number(error?.status || error?.response?.status || 0);
const cancelled = (error) => error?.name === 'CanceledError'
  || error?.name === 'AbortError'
  || error?.code === 'ERR_CANCELED';

function normalizeSnapshot(snapshot, hasThread) {
  const workspace = {
    ...emptyWorkspace(hasThread ? 'absent' : 'unselected'),
    ...(snapshot?.workspace || {}),
    entries: [...(snapshot?.workspace?.entries || [])],
    history: [...(snapshot?.workspace?.history || [])],
  };
  const room = {
    ...emptyRoom(workspace.state === 'ready' ? 'ready' : workspace.state),
    ...(snapshot?.room || {}),
    issues: [...(snapshot?.room?.issues || [])],
    leases: [...(snapshot?.room?.leases || [])],
    activity: [...(snapshot?.room?.activity || [])],
  };
  const library = {
    ...EMPTY_WORK_HUB.library,
    ...(snapshot?.library || {}),
    items: [...(snapshot?.library?.items || [])],
  };
  return {
    contract_version: Number(snapshot?.contract_version || 2),
    loading: false,
    refreshing: false,
    workspace,
    room,
    library,
    history: workspace.history,
  };
}

function mergeLibraryPage(current, incoming) {
  const firstPage = incoming?.items || [];
  const seen = new Set(firstPage.map((item) => item.file_id));
  const retained = (current?.items || []).filter((item) => !seen.has(item.file_id));
  const hadAdditionalPages = (current?.items || []).length > firstPage.length;
  return {
    ...current,
    ...incoming,
    items: [...firstPage, ...retained],
    next_cursor: hadAdditionalPages ? current?.next_cursor : incoming?.next_cursor,
    next_offset: hadAdditionalPages ? current?.next_offset : incoming?.next_offset,
  };
}

export function useWorkSnapshot({ threadId, invalidationVersion = 0, notify }) {
  const [hub, setHub] = useState(() => normalizeSnapshot(null, Boolean(threadId)));
  const [libraryBusy, setLibraryBusy] = useState(false);
  const generationRef = useRef(0);
  const threadRef = useRef(threadId);
  const controllerRef = useRef(null);
  threadRef.current = threadId;

  const applySnapshot = useCallback((
    snapshot,
    expectedThread = threadRef.current,
    { preserveLibrary = false } = {},
  ) => {
    if (threadRef.current !== expectedThread) return null;
    const normalized = normalizeSnapshot(snapshot, Boolean(expectedThread));
    setHub((old) => ({
      ...normalized,
      library: preserveLibrary
        ? mergeLibraryPage(old.library, normalized.library)
        : normalized.library,
    }));
    return normalized.workspace;
  }, []);

  const load = useCallback(async ({ background = false } = {}) => {
    const expectedThread = threadId;
    const generation = ++generationRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setHub((old) => ({
      ...old,
      loading: !background && old.library.items.length === 0 && old.workspace.entries.length === 0,
      refreshing: background || old.library.items.length > 0 || old.workspace.entries.length > 0,
    }));
    try {
      const api = await import('@api/chat');
      const snapshot = expectedThread
        ? await api.getWorkHub(expectedThread, { signal: controller.signal })
        : {
          contract_version: 2,
          workspace: emptyWorkspace('unselected'),
          room: emptyRoom('unselected'),
          library: await api.getAccountWorkLibrary({ signal: controller.signal }),
        };
      if (generation !== generationRef.current || threadRef.current !== expectedThread) return null;
      return applySnapshot(snapshot, expectedThread, { preserveLibrary: background });
    } catch (error) {
      if (cancelled(error) || generation !== generationRef.current || threadRef.current !== expectedThread) return null;
      let library = null;
      try {
        const api = await import('@api/chat');
        library = await api.getAccountWorkLibrary({ signal: controller.signal });
      } catch {
        // Existing library data remains visible when the independent fallback
        // request also fails.
      }
      if (generation !== generationRef.current || threadRef.current !== expectedThread) return null;
      const status = statusOf(error);
      const state = status === 410 ? 'expired' : status === 404 ? 'unselected' : 'unavailable';
      setHub((old) => ({
        ...old,
        loading: false,
        refreshing: false,
        workspace: old.workspace.state === 'ready' && status !== 410
          ? { ...old.workspace, state: 'unavailable' }
          : emptyWorkspace(state),
        room: emptyRoom(state),
        library: library
          ? mergeLibraryPage(old.library, {
            ...EMPTY_WORK_HUB.library,
            ...library,
            state: library.state || 'ready',
          })
          : { ...old.library, state: old.library.items.length ? 'stale' : 'unavailable' },
      }));
      return null;
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [applySnapshot, threadId]);

  useEffect(() => {
    generationRef.current += 1;
    controllerRef.current?.abort();
    setHub(normalizeSnapshot(null, Boolean(threadId)));
    load();
    return () => controllerRef.current?.abort();
  }, [load, threadId]);

  useEffect(() => {
    if (invalidationVersion > 0) load({ background: true });
  }, [invalidationVersion, load]);

  const loadMoreLibrary = useCallback(async () => {
    const cursor = hub.library?.next_cursor;
    const offset = hub.library?.next_offset;
    if (libraryBusy || (cursor == null && offset == null)) return;
    const expectedThread = threadRef.current;
    const generation = generationRef.current;
    setLibraryBusy(true);
    try {
      const { getAccountWorkLibrary } = await import('@api/chat');
      const params = cursor ? { cursor } : { offset };
      const page = await getAccountWorkLibrary({ params });
      if (generation !== generationRef.current || threadRef.current !== expectedThread) return;
      setHub((old) => {
        const known = new Set((old.library.items || []).map((item) => item.file_id));
        const additions = (page?.items || []).filter((item) => !known.has(item.file_id));
        return {
          ...old,
          library: {
            ...old.library,
            ...page,
            state: page?.state || 'ready',
            items: [...old.library.items, ...additions],
          },
        };
      });
    } catch {
      notify?.({
        title: 'Не удалось загрузить следующие файлы',
        status: 'warning',
        duration: 3000,
      });
    } finally {
      if (generation === generationRef.current) setLibraryBusy(false);
    }
  }, [hub.library?.next_cursor, hub.library?.next_offset, libraryBusy, notify]);

  return {
    hub,
    setHub,
    applySnapshot,
    load,
    loadMoreLibrary,
    libraryBusy,
  };
}
