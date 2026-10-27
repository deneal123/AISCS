import { useCallback, useEffect, useRef, useState } from 'react';

const hasProject = workspace => (workspace.entries || []).some(item => /(^|\/)document\.toml$/i.test(item.path || ''));

/** One first-entry request owner. A retry observes the same server-owned intent. */
export function usePdfPreparation({ threadId, active, snapshot, begin, owns, finish, actionBusy, onThreadUnavailable }) {
  const [state, setState] = useState({ threadId, status: 'idle' });
  const attempted = useRef(null);
  const current = useRef(null);
  current.current = { threadId, active, snapshot, onThreadUnavailable };
  const workspace = snapshot.hub.workspace;
  const eligible = Boolean(threadId && !snapshot.hub.loading && !snapshot.hub.refreshing
    && (workspace.state === 'absent' || (workspace.state === 'ready' && !hasProject(workspace))));
  const prepare = useCallback(async ({ retry = false } = {}) => {
    const start = current.current;
    if (!start.active || start.threadId !== threadId) return;
    const ticket = begin(threadId, 'pdf-prepare');
    if (!ticket) return;
    attempted.current = threadId;
    setState({ threadId, status: 'preparing' });
    try {
      const { preparePdfWorkspace } = await import('@api/chat');
      if (!owns(ticket)) return;
      const result = retry ? await preparePdfWorkspace(threadId, { retry: true }) : await preparePdfWorkspace(threadId);
      if (!owns(ticket)) return;
      if (result?.state === 'expired') {
        setState({ threadId, status: 'expired' });
        return;
      }
      if (result?.state !== 'ready' || result.workspace?.state !== 'ready'
        || typeof result.project_path !== 'string' || !result.project_path
        || !result.workspace.revision || !Array.isArray(result.workspace.entries)
        || !result.workspace.entries.some(item => item.path === `${result.project_path}/document.toml`)) {
        throw Error('pdf_preparation_unconfirmed');
      }
      const owner = current.current.snapshot;
      owner.applySnapshot({ ...owner.hub, workspace: result.workspace,
        room: { ...owner.hub.room, state: 'ready' } }, threadId, { preserveLibrary: true });
      setState({ threadId, status: 'ready' });
    } catch (error) {
      if (!owns(ticket)) return;
      const detail = error?.response?.data?.detail || error?.data?.detail;
      if (Number(error?.status || error?.response?.status) === 404
        && (error?.code === 'pdf_project_not_found' || detail === 'pdf_project_not_found')
        && current.current.onThreadUnavailable) {
        current.current.onThreadUnavailable(threadId);
      }
      setState({ threadId, status: 'unavailable' });
    } finally { finish(ticket); }
  }, [begin, finish, owns, threadId]);
  const retryPreparation = useCallback(() => prepare({ retry: true }), [prepare]);
  useEffect(() => {
    let retired = false;
    // StrictMode can retire a mount before the action owner survives it. Defer
    // admission, not a dispatched request; retired effects never start a POST.
    queueMicrotask(() => {
      if (!retired && active && eligible && attempted.current !== threadId && !actionBusy) void prepare();
    });
    return () => { retired = true; };
  }, [active, actionBusy, eligible, prepare, threadId]);
  const status = state.threadId === threadId ? state.status : 'idle';
  const confirmed = workspace.state === 'ready' && hasProject(workspace);
  return { status: active && eligible && attempted.current !== threadId ? 'preparing'
    : confirmed && status !== 'preparing' ? 'ready' : status, retry: retryPreparation };
}
