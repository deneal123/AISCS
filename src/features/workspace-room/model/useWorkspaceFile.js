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
  const currentThreadRef = useRef(threadId);
  const fileRef = useRef(file);
  fileRef.current = file;
  currentThreadRef.current = threadId;
  const dirty = Boolean(file.path && file.content !== file.original);
  const leaseLifecycle = useWorkspaceLease({ threadId, active, notify });

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    generationRef.current += 1;
    setConflict(null);
    setFile(EMPTY_WORK_FILE);
  }, [threadId]);

  useEffect(() => {
    const lease = leaseLifecycle.lease;
    setFile((old) => old.path && old.path === lease.path ? {
      ...old,
      fence: lease.fence,
      leaseStatus: lease.status,
      leaseReason: lease.reason,
    } : old);
  }, [leaseLifecycle.lease]);

  useEffect(() => {
    if (!file.path || !dirty || workspace.state !== 'ready') return;
    if (file.revision && workspace.revision && file.revision !== workspace.revision) {
      setFile((old) => ({ ...old, stale: true }));
    }
  }, [dirty, file.path, file.revision, workspace.revision, workspace.state]);

  const openFile = useCallback(async (path) => {
    const normalizedPath = String(path || '');
    if (!threadId || !normalizedPath || workspace.state !== 'ready') return false;
    if (fileRef.current.path === normalizedPath && !fileRef.current.error) return true;
    const generation = ++generationRef.current;
    const expectedThread = threadId;
    setConflict(null);
    setFile({ ...EMPTY_WORK_FILE, path: normalizedPath, loading: true });
    const lease = await leaseLifecycle.acquire(normalizedPath);
    try {
      const { getWorkspaceFile } = await import('@api/chat');
      const result = await getWorkspaceFile(expectedThread, normalizedPath);
      if (generation !== generationRef.current || currentThreadRef.current !== expectedThread) {
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
      if (lease?.fence) await leaseLifecycle.release({ reason: 'read_failed' });
      if (generation !== generationRef.current || currentThreadRef.current !== expectedThread) return false;
      setFile({
        ...EMPTY_WORK_FILE,
        path: normalizedPath,
        error: true,
        leaseStatus: 'readonly',
        leaseReason: statusOf(error) === 404 ? 'missing' : 'unavailable',
      });
      return false;
    }
  }, [leaseLifecycle, threadId, workspace.revision, workspace.state]);

  const fetchConflict = useCallback(async (status) => {
    const current = fileRef.current;
    if (!threadId || !current.path) return;
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
    } finally {
      setConflict({
        status,
        path: current.path,
        draft: current.content,
        actualContent: actual == null ? null : String(actual.content || ''),
        actualRevision: String(actual?.revision || ''),
        diff,
      });
      setFile((old) => ({ ...old, stale: true }));
    }
  }, [threadId]);

  const save = useCallback(async () => {
    const current = fileRef.current;
    if (!threadId || current.content === current.original || !current.fence || current.truncated) {
      return false;
    }
    setSaving(true);
    try {
      const { writeWorkspaceFile } = await import('@api/chat');
      const result = await writeWorkspaceFile(
        threadId,
        current.path,
        current.content,
        current.revision || workspace.revision,
        current.fence,
        { actorSession: leaseLifecycle.actorSession },
      );
      const revision = String(result?.revision || current.revision || workspace.revision || '');
      // Keep the editor completion seam aligned with the history shown by the
      // Work snapshot.  Until this refresh finishes, the previous history may
      // still point at a commit from before the file existed.
      await refreshSnapshot?.({ background: true });
      setFile((old) => old.path === current.path ? {
        ...old,
        original: old.content,
        revision,
        fence: Number(result?.fence || old.fence),
        stale: false,
      } : old);
      setConflict(null);
      notify?.({ title: 'Изменения сохранены', status: 'success', duration: 2200 });
      return true;
    } catch (error) {
      const status = statusOf(error) || 503;
      if ([409, 423, 503].includes(status)) {
        await fetchConflict(status);
        await refreshSnapshot?.({ background: true });
      }
      notify?.({
        title: status === 409 ? 'Рабочее место изменилось' : 'Сохранить изменения не удалось',
        description: 'Ваш текст остался в редакторе.',
        status: 'warning',
        duration: 4000,
      });
      return false;
    } finally {
      setSaving(false);
    }
  }, [
    fetchConflict,
    leaseLifecycle.actorSession,
    notify,
    refreshSnapshot,
    threadId,
    workspace.revision,
  ]);

  const reacquire = useCallback(async () => {
    if (!fileRef.current.path) return false;
    const next = await leaseLifecycle.reacquire();
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
  }, [leaseLifecycle, notify]);

  const copyDraft = useCallback(async () => {
    const text = conflict?.draft ?? fileRef.current.content;
    try {
      await navigator.clipboard.writeText(text);
      notify?.({ title: 'Ваши изменения скопированы', status: 'success', duration: 2200 });
      return true;
    } catch {
      notify?.({ title: 'Не удалось скопировать текст', status: 'warning', duration: 3000 });
      return false;
    }
  }, [conflict?.draft, notify]);

  const loadActual = useCallback(async () => {
    const currentConflict = conflict;
    if (!currentConflict || currentConflict.actualContent == null) return false;
    await leaseLifecycle.release({ reason: 'reload' });
    const nextLease = await leaseLifecycle.acquire(currentConflict.path);
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
  }, [conflict, leaseLifecycle, workspace.revision]);

  const discard = useCallback(() => {
    setFile((old) => ({ ...old, content: old.original, stale: false }));
    setConflict(null);
  }, []);

  const abandon = useCallback(async () => {
    generationRef.current += 1;
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
  }, [leaseLifecycle]);

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
