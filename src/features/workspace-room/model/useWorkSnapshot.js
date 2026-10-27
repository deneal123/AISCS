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

const pendingSnapshot = (hasThread) => ({ ...normalizeSnapshot(null, hasThread), loading: true });

function retainWorkspace(previous, incoming) {
  if (['unavailable', 'expired', 'absent'].includes(incoming.state)
    && ['ready', 'unavailable', 'expired'].includes(previous.state) && previous.revision) {
    return { ...previous, state: previous.state === 'expired' ? 'expired'
      : incoming.state === 'absent' ? 'unavailable' : incoming.state, stale: true };
  }
  return incoming;
}

export function useWorkSnapshot({ threadId, invalidationVersion = 0, onThreadUnavailable }) {
  const unavailableRef = useRef(onThreadUnavailable);
  unavailableRef.current = onThreadUnavailable;
  const [hub, setHub] = useState(() => pendingSnapshot(Boolean(threadId)));
  const hubThreadRef = useRef(threadId);
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [libraryPageError, setLibraryPageError] = useState(false);
  const generationRef = useRef(0);
  const threadRef = useRef(threadId);
  const controllerRef = useRef(null);
  const pageRef = useRef(null);
  const activeRef = useRef(false);
  const pageLoadRef = useRef(null);
  const observedInvalidation = useRef({ threadId, version: invalidationVersion });
  threadRef.current = threadId;

  const invalidateRequests = useCallback(() => {
    generationRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    pageRef.current?.controller.abort();
    pageRef.current = null;
    setLibraryBusy(false);
  }, []);

  const applySnapshot = useCallback((
    snapshot,
    expectedThread = threadRef.current,
    { preserveLibrary = false, requestGeneration = null } = {},
  ) => {
    if (threadRef.current !== expectedThread) return null;
    if (requestGeneration == null) invalidateRequests();
    else if (requestGeneration !== generationRef.current) return null;
    const normalized = normalizeSnapshot(snapshot, Boolean(expectedThread));
    setHub((old) => {
      const workspace = retainWorkspace(old.workspace, normalized.workspace);
      return { ...normalized, workspace, history: workspace.history,
        library: preserveLibrary ? mergeLibraryPage(old.library, normalized.library) : normalized.library };
    });
    return normalized.workspace;
  }, [invalidateRequests]);

  const load = useCallback(async ({ background = false } = {}) => {
    const expectedThread = threadId;
    if (threadRef.current !== expectedThread) return null;
    invalidateRequests();
    const generation = generationRef.current;
    const controller = new AbortController();
    controllerRef.current = controller;
    setHub((old) => ({
      ...old,
      // An unresolved read cannot become a confirmed empty workspace merely
      // because an invalidation requests a background refresh before it ends.
      loading: old.loading || (!background && old.library.items.length === 0 && old.workspace.entries.length === 0),
      refreshing: !old.loading && (background || old.library.items.length > 0 || old.workspace.entries.length > 0),
    }));
    try {
      const api = await import('@api/chat');
      if (controller.signal.aborted) return null;
      const snapshot = expectedThread
        ? await api.getWorkHub(expectedThread, { signal: controller.signal })
        : {
          contract_version: 2,
          workspace: emptyWorkspace('unselected'),
          room: emptyRoom('unselected'),
          library: await api.getAccountWorkLibrary({ signal: controller.signal }),
        };
      if (generation !== generationRef.current || threadRef.current !== expectedThread) return null;
      return applySnapshot(snapshot, expectedThread, {
        preserveLibrary: background,
        requestGeneration: generation,
      });
    } catch (error) {
      if (cancelled(error) || generation !== generationRef.current || threadRef.current !== expectedThread) return null;
      if (statusOf(error) === 404 && unavailableRef.current) {
        setHub(pendingSnapshot(Boolean(expectedThread)));
        unavailableRef.current(expectedThread);
        return null;
      }
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
        workspace: retainWorkspace(old.workspace, emptyWorkspace(state)),
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
  }, [applySnapshot, invalidateRequests, threadId]);

  useEffect(() => {
    activeRef.current = true;
    hubThreadRef.current = threadId;
    invalidateRequests();
    setLibraryPageError(false);
    setHub(pendingSnapshot(Boolean(threadId)));
    load();
    return () => {
      activeRef.current = false;
      invalidateRequests();
    };
  }, [invalidateRequests, load, threadId]);

  useEffect(() => {
    const previous = observedInvalidation.current;
    observedInvalidation.current = { threadId, version: invalidationVersion };
    // Mount/thread entry already owns its initial read. Only a newly observed
    // same-thread invalidation can retire that read and request fresher facts.
    if (previous.threadId === threadId && previous.version !== invalidationVersion
      && invalidationVersion > 0) load({ background: true });
  }, [invalidationVersion, load, threadId]);

  const loadMoreLibrary = useCallback(async function loadLibraryPage() {
    // A retained control/continuation callback must not replay a previous
    // cursor or start a request in another thread or after unmount.
    if (!activeRef.current || pageLoadRef.current !== loadLibraryPage
      || threadRef.current !== threadId) return;
    const cursor = hub.library?.next_cursor;
    const offset = hub.library?.next_offset;
    if (pageRef.current || (cursor == null && offset == null)) return;
    const expectedThread = threadRef.current;
    const generation = generationRef.current;
    const operation = { controller: new AbortController() };
    pageRef.current = operation;
    const ownsRequest = () => activeRef.current
      && pageLoadRef.current === loadLibraryPage
      && pageRef.current === operation
      && !operation.controller.signal.aborted
      && generation === generationRef.current
      && threadRef.current === expectedThread;
    setLibraryBusy(true);
    try {
      const { getAccountWorkLibrary } = await import('@api/chat');
      if (!ownsRequest()) return;
      const params = cursor ? { cursor } : { offset };
      const page = await getAccountWorkLibrary({ params, signal: operation.controller.signal });
      if (!ownsRequest()) return;
      setLibraryPageError(false);
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
    } catch (error) {
      if (!ownsRequest() || cancelled(error)) return;
      setLibraryPageError(true);
    } finally {
      if (pageRef.current === operation) {
        pageRef.current = null;
        setLibraryBusy(false);
      }
    }
  }, [hub.library?.next_cursor, hub.library?.next_offset, threadId]);
  pageLoadRef.current = loadMoreLibrary;

  return {
    hub: hubThreadRef.current === threadId ? hub : pendingSnapshot(Boolean(threadId)),
    setHub,
    applySnapshot,
    load,
    loadMoreLibrary,
    libraryBusy,
    libraryPageError,
  };
}
