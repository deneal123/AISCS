import { useCallback, useEffect, useMemo, useState } from 'react';
import { useWorkCollaboration } from './useWorkCollaboration';
import { useDocumentForge } from './useDocumentForge';
import { useWorkIssues } from './useWorkIssues';
import { useWorkSnapshot } from './useWorkSnapshot';
import { useWorkUpload } from './useWorkUpload';
import { EMPTY_WORK_FILE, useWorkspaceFile } from './useWorkspaceFile';
import { getWorkspaceActorSession } from './workspaceSession';

const statusOf = (error) => Number(error?.status || error?.response?.status || 0);

export function useWorkHub({
  threadId,
  invalidationVersion = 0,
  notify,
  onCancelRun,
  onDirtyChange,
  active = true,
}) {
  const actorSession = getWorkspaceActorSession();
  const snapshot = useWorkSnapshot({ threadId, invalidationVersion, notify });
  const [actionBusy, setActionBusy] = useState('');
  const [revert, setRevert] = useState(null);
  const [libraryOutcomes, setLibraryOutcomes] = useState({});

  useEffect(() => setLibraryOutcomes({}), [threadId]);
  const workspaceFile = useWorkspaceFile({
    threadId,
    workspace: snapshot.hub.workspace,
    active,
    notify,
    refreshSnapshot: snapshot.load,
    onDirtyChange,
  });
  const issues = useWorkIssues({
    threadId,
    workspaceState: snapshot.hub.workspace.state,
  });
  const collaboration = useWorkCollaboration({
    threadId,
    workspace: snapshot.hub.workspace,
    refreshIssues: issues.load,
    refreshSnapshot: snapshot.load,
    notify,
    onCancelRun,
  });
  const uploader = useWorkUpload({ threadId, refreshSnapshot: snapshot.load, notify });
  const document = useDocumentForge({
    threadId,
    workspace: snapshot.hub.workspace,
    library: snapshot.hub.library,
    selectedPath: workspaceFile.file.path,
    refreshSnapshot: snapshot.load,
    notify,
    onOpenSource: workspaceFile.openFile,
  });

  const activateWorkspace = useCallback(async () => {
    if (!threadId) return null;
    setActionBusy('activate');
    try {
      const { activateWorkHub } = await import('@api/chat');
      const next = await activateWorkHub(threadId);
      const workspace = snapshot.applySnapshot(next, threadId);
      notify?.({ title: 'Рабочее место готово', status: 'success', duration: 2200 });
      return workspace;
    } catch {
      notify?.({
        title: 'Не удалось создать рабочее место',
        description: 'Библиотека остаётся доступной.',
        status: 'warning',
        duration: 3500,
      });
      await snapshot.load({ background: true });
      return null;
    } finally {
      setActionBusy('');
    }
  }, [notify, snapshot, threadId]);

  const copyFromLibrary = useCallback(async (item) => {
    if (!threadId || !item?.file_id) return false;
    setActionBusy(`copy:${item.file_id}`);
    let lease = null;
    try {
      const api = await import('@api/chat');
      let workspace = snapshot.hub.workspace;
      if (workspace.state !== 'ready') {
        const activated = await api.activateWorkHub(threadId);
        workspace = snapshot.applySnapshot(activated, threadId);
      }
      if (workspace?.state !== 'ready') throw new Error('workspace unavailable');
      lease = await api.acquireWorkspaceLease(threadId, item.name, { actorSession });
      const result = await api.copyLibraryFileToWorkspace(
        threadId,
        item.file_id,
        workspace.revision,
        Number(lease?.fence || 0),
        { actorSession },
      );
      if (result?.outcome === 'imported') {
        notify?.({ title: 'Файл добавлен в рабочее место', status: 'success', duration: 2500 });
      } else {
        notify?.({
          title: 'В рабочем месте уже есть файл с этим именем',
          status: 'info',
          duration: 3200,
        });
      }
      setLibraryOutcomes((previous) => ({
        ...previous,
        [item.file_id]: result?.outcome === 'imported' ? 'imported' : 'kept',
      }));
      await snapshot.load({ background: true });
      return true;
    } catch (error) {
      const copyStatus = statusOf(error);
      const copyOutcome = copyStatus === 409
        ? 'conflict'
        : copyStatus === 423 ? 'busy' : 'unavailable';
      setLibraryOutcomes((previous) => ({
        ...previous,
        [item.file_id]: copyOutcome,
      }));
      notify?.({
        title: statusOf(error) === 409 ? 'Рабочее место изменилось' : 'Добавить файл не удалось',
        description: 'Файл в библиотеке не изменён.',
        status: 'warning',
        duration: 3500,
      });
      await snapshot.load({ background: true });
      return false;
    } finally {
      if (lease?.fence) {
        try {
          const { releaseWorkspaceLease } = await import('@api/chat');
          await releaseWorkspaceLease(threadId, item.name, Number(lease.fence), {
            actorSession,
          });
        } catch {
          // Server TTL bounds a best-effort release.
        }
      }
      setActionBusy('');
    }
  }, [actorSession, notify, snapshot, threadId]);

  const previewRevert = useCallback(async (ref) => {
    if (!threadId) return;
    setActionBusy(`diff:${ref}`);
    try {
      const { getWorkspaceDiff } = await import('@api/chat');
      const result = await getWorkspaceDiff(threadId, ref, '');
      setRevert({ ref, diff: String(result?.diff || '') });
    } catch {
      notify?.({
        title: 'Не удалось загрузить изменения перед откатом',
        status: 'warning',
        duration: 3000,
      });
    } finally {
      setActionBusy('');
    }
  }, [notify, threadId]);

  const applyRevert = useCallback(async () => {
    if (!threadId || !revert) return false;
    if (workspaceFile.dirty) {
      notify?.({
        title: 'Сначала сохраните или скопируйте изменения редактора',
        status: 'warning',
        duration: 3500,
      });
      return false;
    }
    setActionBusy(`revert:${revert.ref}`);
    try {
      const { revertWorkspace } = await import('@api/chat');
      // A background snapshot may still carry the revision from before the
      // editor's just-completed write. The write response is the newest
      // coherent mutation result, so prefer its revision at the revert seam.
      const expectedRevision = workspaceFile.file.revision || snapshot.hub.workspace.revision;
      await revertWorkspace(threadId, revert.ref, expectedRevision, '', { actorSession });
      await workspaceFile.releaseLease({ reason: 'revert' });
      workspaceFile.setFile(EMPTY_WORK_FILE);
      setRevert(null);
      await snapshot.load({ background: true });
      notify?.({
        title: 'Рабочее место возвращено к снимку',
        status: 'success',
        duration: 2500,
      });
      return true;
    } catch (error) {
      setRevert(null);
      notify?.({
        title: statusOf(error) === 409 ? 'Рабочее место изменилось' : 'Откат не выполнен',
        description: 'Состояние перечитано без перезаписи редактора.',
        status: 'warning',
        duration: 3500,
      });
      await snapshot.load({ background: true });
      return false;
    } finally {
      setActionBusy('');
    }
  }, [actorSession, notify, revert, snapshot, threadId, workspaceFile]);

  const createIssue = useCallback((payload) => collaboration.createIssue({
    ...payload,
    file: workspaceFile.file,
  }), [collaboration, workspaceFile.file]);

  const busy = actionBusy
    || collaboration.busy
    || (workspaceFile.saving ? 'save' : '')
    || (uploader.busy ? 'upload' : '')
    || (snapshot.libraryBusy ? 'library:more' : '');
  const hub = useMemo(() => ({
    ...snapshot.hub,
    room: {
      ...snapshot.hub.room,
      issues: issues.items,
      issuesState: issues.status,
    },
    history: snapshot.hub.workspace.history || [],
  }), [issues.items, issues.status, snapshot.hub]);

  return useMemo(() => ({
    hub,
    file: workspaceFile.file,
    setFile: workspaceFile.setFile,
    busy,
    dirty: workspaceFile.dirty,
    conflict: workspaceFile.conflict,
    libraryOutcomes,
    revert,
    setRevert,
    load: snapshot.load,
    openFile: workspaceFile.openFile,
    save: workspaceFile.save,
    discard: workspaceFile.discard,
    abandonDraft: workspaceFile.abandon,
    reacquireLease: workspaceFile.reacquire,
    copyDraft: workspaceFile.copyDraft,
    loadActual: workspaceFile.loadActual,
    activateWorkspace,
    copyFromLibrary,
    uploadToWorkspace: uploader.upload,
    uploadResult: uploader.lastResult,
    loadMoreLibrary: snapshot.loadMoreLibrary,
    previewRevert,
    applyRevert,
    createIssue,
    updateIssue: collaboration.updateIssue,
    controlAgent: collaboration.controlAgent,
    document,
  }), [
    activateWorkspace,
    applyRevert,
    busy,
    collaboration.controlAgent,
    collaboration.updateIssue,
    copyFromLibrary,
    createIssue,
    document,
    hub,
    libraryOutcomes,
    previewRevert,
    revert,
    snapshot.load,
    snapshot.loadMoreLibrary,
    uploader.lastResult,
    uploader.upload,
    workspaceFile,
  ]);
}
