import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkspaceLease } from './useWorkspaceLease';

export const EMPTY_WORK_FILE = {
  path: '',
  content: '',
  original: '',
  revision: '',
  fence: 0,
  leaseStatus: 'idle',
  leaseReason: '',
  loading: false,
  error: false,
  truncated: false,
  stale: false,
};

const statusOf = (error) => Number(error?.status || error?.response?.status || 0);

export function useWorkspaceFile({
  threadId,
  workspace,
  active = true,
  notify,
  refreshSnapshot,
  onDirtyChange,
}) {
  const [file, setFile] = useState(EMPTY_WORK_FILE);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(null);
  const generationRef = useRef(0);
  const saveRef = useRef(null);
  const recoveryRef = useRef(null);
  const activeRef = useRef(active);
  const mountedRef = useRef(true);
  const workspaceStateRef = useRef(workspace.state);
  const currentThreadRef = useRef(threadId);
  const scopeRef = useRef({ threadId });
  if (scopeRef.current.threadId !== threadId) scopeRef.current = { threadId };
  const owner = scopeRef.current;
  const fileRef = useRef(file);
  fileRef.current = file;
  currentThreadRef.current = threadId;
  activeRef.current = active;
  workspaceStateRef.current = workspace.state;
  const dirty = Boolean(file.path && file.content !== file.original);
  const leaseLifecycle = useWorkspaceLease({ threadId, active, notify });

  const ownsScope = useCallback(() => mountedRef.current && scopeRef.current === owner, [owner]);
  const canStartAction = useCallback(() => ownsScope() && activeRef.current
    && Boolean(threadId), [ownsScope, threadId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    generationRef.current += 1;
    saveRef.current = null;
    recoveryRef.current = null;
    setSaving(false);
    setConflict(null);
    setFile(EMPTY_WORK_FILE);
    return () => { generationRef.current += 1; };
  }, [threadId]);

  useEffect(() => {
    if (!active) recoveryRef.current = null;
  }, [active]);

  useEffect(() => {
    const lease = leaseLifecycle.lease;
    setFile((old) => old.path && old.path === lease.path && lease.threadId === threadId ? {
      ...old,
      fence: lease.fence,
      leaseStatus: lease.status,
      leaseReason: lease.reason,
    } : old);
  }, [leaseLifecycle.lease, threadId]);

  useEffect(() => {
    if (!file.path || !dirty || workspace.state !== 'ready') return;
    if (file.revision && workspace.revision && file.revision !== workspace.revision) {
      setFile((old) => ({ ...old, stale: true }));
    }
  }, [dirty, file.path, file.revision, workspace.revision, workspace.state]);

  const openFile = useCallback(async (path) => {
    const normalizedPath = String(path || '');
    // Reject captured callbacks before touching the current editor or invalidating
    // another file's request. A late response guard alone cannot protect a draft.
    if (!canStartAction() || !normalizedPath || workspaceStateRef.current !== 'ready') return false;
    if (fileRef.current.path === normalizedPath && !fileRef.current.error) return true;
    const generation = ++generationRef.current;
    saveRef.current = null;
    recoveryRef.current = null;
    setSaving(false);
    const expectedThread = threadId;
    const isCurrent = () => mountedRef.current && generation === generationRef.current
      && currentThreadRef.current === expectedThread;
    setConflict(null);
    setFile({ ...EMPTY_WORK_FILE, path: normalizedPath, loading: true });
    const lease = await leaseLifecycle.acquire(normalizedPath);
    try {
      const { getWorkspaceFile } = await import('@api/chat');
      if (!isCurrent()) {
        await leaseLifecycle.releaseTarget(lease);
        return false;
      }
      const result = await getWorkspaceFile(expectedThread, normalizedPath);
      if (!isCurrent()) {
        await leaseLifecycle.releaseTarget(lease);
        return false;
      }
      const content = String(result?.content || '');
      setFile({
        ...EMPTY_WORK_FILE,
        path: normalizedPath,
        content,
        original: content,
        revision: String(result?.revision || workspace.revision || ''),
        fence: Number(lease?.fence || 0),
        leaseStatus: lease?.status || 'readonly',
        leaseReason: lease?.reason || '',
        truncated: Boolean(result?.truncated),
      });
      return true;
    } catch (error) {
      if (!isCurrent()) {
        await leaseLifecycle.releaseTarget(lease);
        return false;
      }
      if (lease?.fence) await leaseLifecycle.release({ reason: 'read_failed' });
      if (!isCurrent()) return false;
      setFile({
        ...EMPTY_WORK_FILE,
        path: normalizedPath,
        error: true,
        leaseStatus: 'readonly',
        leaseReason: statusOf(error) === 404 ? 'missing' : 'unavailable',
      });
      return false;
    }
  }, [canStartAction, leaseLifecycle, threadId, workspace.revision]);

  const fetchConflict = useCallback(async (status, current, isCurrent) => {
    if (!isCurrent()) return;
    let actual = null;
    let diff = '';
    try {
      const api = await import('@api/chat');
      [actual, diff] = await Promise.all([
        api.getWorkspaceFile(threadId, current.path).catch(() => null),
        current.revision
          ? api.getWorkspaceDiff(threadId, current.revision, current.path)
            .then((value) => String(value?.diff || '')).catch(() => '')
          : Promise.resolve(''),
      ]);
    } catch {
      // Recovery remains available even when the current version cannot be read.
    }
    if (!isCurrent()) return;
    setConflict({
      status,
      path: current.path,
      draft: fileRef.current.content,
      actualContent: actual == null ? null : String(actual.content || ''),
      actualRevision: String(actual?.revision || ''),
      diff,
    });
    setFile((old) => ({ ...old, stale: true }));
  }, [threadId]);

  const save = useCallback(async () => {
    if (!canStartAction()) return false;
    const current = fileRef.current;
    if (!threadId || saveRef.current || recoveryRef.current || current.content === current.original || !current.fence || current.truncated) {
      return false;
    }
    const operation = { generation: generationRef.current, threadId, path: current.path };
    const isCurrent = () => saveRef.current === operation
      && generationRef.current === operation.generation
      && currentThreadRef.current === operation.threadId
      && fileRef.current.path === operation.path;
    saveRef.current = operation;
    setSaving(true);
    try {
      const { writeWorkspaceFile } = await import('@api/chat');
      if (!isCurrent() || !canStartAction()) return false;
      const result = await writeWorkspaceFile(
        threadId,
        current.path,
        current.content,
        current.revision || workspace.revision,
        current.fence,
        { actorSession: leaseLifecycle.actorSession },
      );
      if (!isCurrent()) return false;
      const revision = String(result?.revision || current.revision || workspace.revision || '');
      setFile((old) => old.path === current.path ? {
        ...old,
        original: current.content,
        revision,
        fence: Number(result?.fence || old.fence),
        stale: false,
      } : old);
      setConflict(null);
      notify?.({ title: 'Изменения сохранены', status: 'success', duration: 2200 });
      // The write receipt owns the persisted baseline and next revision.
      // Tree/history refresh has its own generation guard and visible status;
      // its latency or failure must not hold the editor's save operation open.
      try {
        Promise.resolve(refreshSnapshot?.({ background: true })).catch(() => {});
      } catch { /* Snapshot recovery is independent from the acknowledged write. */ }
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      const status = statusOf(error) || 503;
      if ([409, 423, 503].includes(status)) {
        await fetchConflict(status, current, isCurrent);
        if (!isCurrent()) return false;
        try { await refreshSnapshot?.({ background: true }); } catch { /* Preserve the draft. */ }
      }
      if (!isCurrent()) return false;
      notify?.({
        title: status === 409 ? 'Рабочее место изменилось' : 'Сохранить изменения не удалось',
        description: 'Ваш текст остался в редакторе.',
        status: 'warning',
        duration: 4000,
      });
      return false;
    } finally {
      if (saveRef.current === operation) {
        saveRef.current = null;
        setSaving(false);
      }
    }
  }, [
    canStartAction,
    fetchConflict,
    leaseLifecycle.actorSession,
    notify,
    refreshSnapshot,
    threadId,
    workspace.revision,
  ]);

  const reacquire = useCallback(async () => {
    if (!canStartAction()) return false;
    const current = fileRef.current;
    if (!activeRef.current || !current.path || recoveryRef.current || saveRef.current) return false;
    const operation = { generation: generationRef.current, threadId, path: current.path };
    const isCurrent = () => recoveryRef.current === operation && canStartAction()
      && generationRef.current === operation.generation && currentThreadRef.current === threadId
      && fileRef.current.path === current.path;
    recoveryRef.current = operation;
    try {
      const next = await leaseLifecycle.reacquire();
      if (!isCurrent()) {
        await leaseLifecycle.releaseTarget(next);
        return false;
      }
      if (!next.fence) {
        notify?.({
          title: 'Файл всё ещё занят',
          description: 'Он открыт только для чтения; ваш текст не изменён.',
          status: 'info',
          duration: 3500,
        });
        return false;
      }
      setFile((old) => ({
        ...old, fence: next.fence, leaseStatus: 'editing', leaseReason: '',
      }));
      return true;
    } finally {
      if (recoveryRef.current === operation) recoveryRef.current = null;
    }
  }, [canStartAction, leaseLifecycle, notify, threadId]);

  const copyDraft = useCallback(async () => {
    if (!canStartAction() || !fileRef.current.path) return false;
    const generation = generationRef.current;
    const path = fileRef.current.path;
    const isCurrent = () => canStartAction() && generation === generationRef.current
      && fileRef.current.path === path;
    const text = fileRef.current.content;
    try {
      await navigator.clipboard.writeText(text);
      if (!isCurrent()) return false;
      notify?.({ title: 'Ваши изменения скопированы', status: 'success', duration: 2200 });
      return true;
    } catch {
      if (!isCurrent()) return false;
      notify?.({ title: 'Не удалось скопировать текст', status: 'warning', duration: 3000 });
      return false;
    }
  }, [canStartAction, notify]);

  const loadActual = useCallback(async () => {
    if (!canStartAction()) return false;
    const currentConflict = conflict;
    const current = fileRef.current;
    if (!activeRef.current || recoveryRef.current || saveRef.current || !currentConflict
      || currentConflict.actualContent == null || currentConflict.path !== current.path) return false;
    const operation = { generation: generationRef.current, threadId, path: current.path };
    const isCurrent = () => recoveryRef.current === operation && canStartAction()
      && generationRef.current === operation.generation && currentThreadRef.current === threadId
      && fileRef.current.path === current.path;
    recoveryRef.current = operation;
    try {
      await leaseLifecycle.release({ reason: 'reload' });
      if (!isCurrent()) return false;
      const nextLease = await leaseLifecycle.acquire(currentConflict.path);
      if (!isCurrent()) {
        await leaseLifecycle.releaseTarget(nextLease);
        return false;
      }
      // Loading the reviewed version is explicit, but does not discard text typed
      // after that action while the new lease was being acquired.
      if (fileRef.current.content !== current.content) return false;
      setFile({
        ...EMPTY_WORK_FILE,
        path: currentConflict.path,
        content: currentConflict.actualContent,
        original: currentConflict.actualContent,
        revision: currentConflict.actualRevision || workspace.revision,
        fence: Number(nextLease.fence || 0),
        leaseStatus: nextLease.status,
        leaseReason: nextLease.reason,
      });
      setConflict(null);
      return true;
    } finally {
      if (recoveryRef.current === operation) recoveryRef.current = null;
    }
  }, [canStartAction, conflict, leaseLifecycle, threadId, workspace.revision]);

  const discard = useCallback(() => {
    if (!canStartAction()) return false;
    setFile((old) => ({ ...old, content: old.original, stale: false }));
    setConflict(null);
    return true;
  }, [canStartAction]);

  const abandon = useCallback(async () => {
    // Confirmed navigation may finish after Work becomes inactive, but never
    // in another thread or after this owner unmounts.
    if (!ownsScope()) return false;
    generationRef.current += 1;
    saveRef.current = null;
    recoveryRef.current = null;
    setSaving(false);
    const current = fileRef.current;
    const next = current.path ? {
      ...current,
      content: current.original,
      fence: 0,
      leaseStatus: 'lost',
      leaseReason: 'navigation',
      loading: false,
      stale: false,
    } : EMPTY_WORK_FILE;
    fileRef.current = next;
    setFile(next);
    setConflict(null);
    try {
      await leaseLifecycle.release({ reason: 'navigation' });
    } catch {
      // The server-side lease TTL bounds best-effort navigation cleanup.
    }
    return true;
  }, [leaseLifecycle, ownsScope]);

  return {
    file,
    setFile,
    dirty,
    saving,
    conflict,
    setConflict,
    openFile,
    save,
    discard,
    abandon,
    reacquire,
    copyDraft,
    loadActual,
    releaseLease: leaseLifecycle.release,
    actorSession: leaseLifecycle.actorSession,
  };
}
