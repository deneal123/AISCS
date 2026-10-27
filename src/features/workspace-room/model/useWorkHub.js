import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useWorkCollaboration } from './useWorkCollaboration';
import { useDocumentForge } from './useDocumentForge';
import { useWorkIssues } from './useWorkIssues';
import { useWorkIssueDraft } from './useWorkIssueDraft';
import { useWorkSnapshot } from './useWorkSnapshot';
import { useWorkUpload } from './useWorkUpload';
import { useWorkActionOwner } from './useWorkActionOwner';
import { usePdfPreparation } from './usePdfPreparation';
import { EMPTY_WORK_FILE, useWorkspaceFile } from './useWorkspaceFile';
import { getWorkspaceActorSession } from './workspaceSession';
import { projectImageOptions } from './documentAssets';

const statusOf = (error) => Number(error?.status || error?.response?.status || 0);

export function useWorkHub({
  threadId,
  assistantRunning = false,
  invalidationVersion = 0,
  notify,
  onCancelRun,
  onDirtyChange,
  onThreadUnavailable,
  active = true,
  libraryActive = false,
  pdfActive = false,
}) {
  const actorSession = getWorkspaceActorSession();
  const [completionVersion, setCompletionVersion] = useState(0);
  const previousRun = useRef(null);
  useEffect(() => {
    if (previousRun.current?.threadId === threadId && previousRun.current.running && !assistantRunning) {
      setCompletionVersion((version) => version + 1);
    }
    previousRun.current = { threadId, running: assistantRunning };
  }, [assistantRunning, threadId]);
  const refreshVersion = invalidationVersion + completionVersion;
  const snapshot = useWorkSnapshot({ threadId, invalidationVersion: refreshVersion, notify, onThreadUnavailable });
  const workActive = useRef(active);
  workActive.current = active;
  const { busy: actionBusy, begin, owns, finish } = useWorkActionOwner({ threadId, active: active || libraryActive });
  const pdfPreparation = usePdfPreparation({ threadId, active: pdfActive, snapshot,
    begin, owns, finish, actionBusy, onThreadUnavailable });
  const [revert, setRevert] = useState(null);
  const [libraryOutcomes, setLibraryOutcomes] = useState({});

  useEffect(() => {
    setLibraryOutcomes({});
    setRevert(null);
  }, [threadId]);
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
  const issueDraft = useWorkIssueDraft(threadId, workspaceFile.file.path);
  const collaboration = useWorkCollaboration({
    threadId,
    active,
    workspace: snapshot.hub.workspace,
    refreshIssues: issues.load,
    refreshSnapshot: snapshot.load,
    notify,
    onCancelRun,
  });
  const uploader = useWorkUpload({ threadId, refreshSnapshot: snapshot.load, notify });
  const document = useDocumentForge({
    threadId,
    invalidationVersion: refreshVersion,
    active,
    workspace: snapshot.hub.workspace,
    library: snapshot.hub.library,
    selectedPath: workspaceFile.file.path,
    refreshSnapshot: snapshot.load,
    notify,
    onOpenSource: workspaceFile.openFile,
  });
  const copyTarget = useRef(null);
  copyTarget.current = { threadId, active: active || libraryActive, path: document.project?.path };
  const projectRevision = document.project?.revision;
  const { loadProject: reloadDocument, loadAuthoring: reloadDocumentAuthoring } = document;

  const refreshActionSnapshot = useCallback(async (ticket) => {
    if (!owns(ticket)) return;
    try {
      await snapshot.load({ background: true });
    } catch {
      // The read owner handles availability. A failed refresh cannot revoke
      // an already confirmed mutation or request that mutation again.
    }
  }, [owns, snapshot]);

  const activateWorkspace = useCallback(async () => {
    if (!workActive.current) return null;
    const ticket = begin(threadId, 'activate');
    if (!ticket) return null;
    try {
      const { activateWorkHub } = await import('@api/chat');
      if (!owns(ticket)) return null;
      const next = await activateWorkHub(threadId);
      if (!owns(ticket)) return null;
      const workspace = snapshot.applySnapshot(next, threadId);
      if (workspace?.state !== 'ready') throw new Error('workspace_activation_incomplete');
      notify?.({ title: 'Рабочее место готово', status: 'success', duration: 2200 });
      return workspace;
    } catch {
      if (!owns(ticket)) return null;
      notify?.({
        title: 'Не удалось создать рабочее место',
        description: 'Библиотека остаётся доступной.',
        status: 'warning',
        duration: 3500,
      });
      await refreshActionSnapshot(ticket);
      return null;
    } finally {
      finish(ticket);
    }
  }, [begin, finish, owns, notify, refreshActionSnapshot, snapshot, threadId]);

  const copyFromLibrary = useCallback(async (item, options = {}) => {
    if (!threadId || !item?.file_id) return false;
    const documentPath = options.documentPath;
    const currentTarget = () => !documentPath || (copyTarget.current.active
      && copyTarget.current.threadId === threadId && copyTarget.current.path === documentPath);
    if (!currentTarget() || (documentPath && snapshot.hub.workspace.state !== 'ready')) return false;
    const ticket = begin(threadId, `copy:${item.file_id}`);
    if (!ticket) return false;
    let lease = null;
    const leasePath = documentPath || item.name;
    const outcomeKey = documentPath ? `${documentPath}/${item.file_id}` : item.file_id;
    const ownsTarget = () => owns(ticket) && currentTarget();
    try {
      const api = await import('@api/chat');
      if (!ownsTarget()) return false;
      let workspace = snapshot.hub.workspace;
      const observedRevision = workspace.state === 'ready' ? workspaceFile.file.revision : '';
      if (workspace.state !== 'ready') {
        const activated = await api.activateWorkHub(threadId);
        if (!owns(ticket)) return false;
        workspace = snapshot.applySnapshot(activated, threadId);
      }
      if (workspace?.state !== 'ready') throw new Error('workspace unavailable');
      lease = await api.acquireWorkspaceLease(threadId, leasePath, { actorSession });
      if (!ownsTarget()) return false;
      const result = await api.copyLibraryFileToWorkspace(
        threadId,
        item.file_id,
        // An acknowledged edit is newer than a lagging background snapshot.
        // Server revision preflight still rejects any intervening mutation.
        documentPath ? projectRevision : observedRevision || workspace.revision,
        Number(lease?.fence || 0),
        { actorSession, ...(documentPath ? { documentPath } : {}) },
      );
      if (!ownsTarget()) return false;
      if (result?.outcome !== 'imported' && result?.outcome !== 'kept') {
        throw new Error('workspace_copy_incomplete');
      }
      if (documentPath && !projectImageOptions([{ type: 'file', path: `${documentPath}/${result.asset_path}` }], documentPath).length) {
        throw new Error('document_asset_unconfirmed');
      }
      if (result?.outcome === 'imported') {
        notify?.({ title: documentPath ? 'Изображение добавлено в PDF-проект' : 'Файл добавлен в рабочее место', status: 'success', duration: 2500 });
      } else {
        notify?.({
          title: documentPath ? 'Этот файл уже есть в PDF-проекте' : 'В рабочем месте уже есть файл с этим именем',
          status: 'info',
          duration: 3200,
        });
      }
      setLibraryOutcomes((previous) => ({
        ...previous,
        [outcomeKey]: result?.outcome === 'imported' ? 'imported' : 'kept',
      }));
      if (documentPath) {
        try {
          const refreshed = await reloadDocument(documentPath);
          if (ownsTarget() && refreshed) await reloadDocumentAuthoring(documentPath);
        } catch {
          // Read recovery is separate from the already acknowledged asset import.
        }
      }
      await refreshActionSnapshot(ticket);
      return true;
    } catch (error) {
      if (!ownsTarget()) return false;
      const copyStatus = statusOf(error);
      const copyOutcome = copyStatus === 409
        ? 'conflict'
        : copyStatus === 423 ? 'busy' : 'unavailable';
      setLibraryOutcomes((previous) => ({
        ...previous,
        [outcomeKey]: copyOutcome,
      }));
      notify?.({
        title: statusOf(error) === 409 ? 'Рабочее место изменилось' : 'Добавить файл не удалось',
        description: 'Файл в библиотеке не изменён.',
        status: 'warning',
        duration: 3500,
      });
      await refreshActionSnapshot(ticket);
      return false;
    } finally {
      if (lease?.fence) {
        try {
          const { releaseWorkspaceLease } = await import('@api/chat');
          await releaseWorkspaceLease(threadId, leasePath, Number(lease.fence), {
            actorSession,
          });
        } catch {
          // Server TTL bounds a best-effort release.
        }
      }
      finish(ticket);
    }
  }, [actorSession, begin, finish, owns, notify, projectRevision, refreshActionSnapshot, reloadDocument, reloadDocumentAuthoring, snapshot,
    threadId, workspaceFile.file.revision]);

  const previewRevert = useCallback(async (ref) => {
    if (!workActive.current) return;
    const ticket = begin(threadId, `diff:${ref}`);
    if (!ticket) return;
    try {
      const { getWorkspaceDiff } = await import('@api/chat');
      if (!owns(ticket)) return;
      const result = await getWorkspaceDiff(threadId, ref, '');
      if (!owns(ticket)) return;
      setRevert({ ref, diff: String(result?.diff || '') });
    } catch {
      if (!owns(ticket)) return;
      notify?.({
        title: 'Не удалось загрузить изменения перед откатом',
        status: 'warning',
        duration: 3000,
      });
    } finally {
      finish(ticket);
    }
  }, [begin, finish, owns, notify, threadId]);

  const applyRevert = useCallback(async () => {
    if (!workActive.current) return false;
    if (!threadId || !revert) return false;
    const ticket = begin(threadId, `revert:${revert.ref}`);
    if (!ticket) return false;
    if (workspaceFile.dirty) {
      notify?.({
        title: 'Сначала сохраните или скопируйте изменения редактора',
        status: 'warning',
        duration: 3500,
      });
      finish(ticket);
      return false;
    }
    try {
      const { revertWorkspace } = await import('@api/chat');
      if (!owns(ticket)) return false;
      // A background snapshot may still carry the revision from before the
      // editor's just-completed write. The write response is the newest
      // coherent mutation result, so prefer its revision at the revert seam.
      const expectedRevision = workspaceFile.file.revision || snapshot.hub.workspace.revision;
      await revertWorkspace(threadId, revert.ref, expectedRevision, '', { actorSession });
      if (!owns(ticket)) return false;
      await workspaceFile.releaseLease({ reason: 'revert' });
      if (!owns(ticket)) return false;
      workspaceFile.setFile(EMPTY_WORK_FILE);
      setRevert(null);
      await refreshActionSnapshot(ticket);
      if (!owns(ticket)) return false;
      notify?.({
        title: 'Рабочее место возвращено к снимку',
        status: 'success',
        duration: 2500,
      });
      return true;
    } catch (error) {
      if (!owns(ticket)) return false;
      setRevert(null);
      notify?.({
        title: statusOf(error) === 409 ? 'Рабочее место изменилось' : 'Откат не выполнен',
        description: 'Состояние перечитано без перезаписи редактора.',
        status: 'warning',
        duration: 3500,
      });
      await refreshActionSnapshot(ticket);
      return false;
    } finally {
      finish(ticket);
    }
  }, [actorSession, begin, finish, owns, notify, refreshActionSnapshot,
    revert, snapshot, threadId, workspaceFile]);

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
    issueDraft,
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
    libraryPageError: snapshot.libraryPageError,
    previewRevert,
    applyRevert,
    createIssue,
    updateIssue: collaboration.updateIssue,
    controlAgent: collaboration.controlAgent,
    document,
    pdfPreparation,
  }), [
    activateWorkspace,
    applyRevert,
    busy,
    collaboration.controlAgent,
    collaboration.updateIssue,
    copyFromLibrary,
    createIssue,
    document,
    pdfPreparation,
    hub,
    issueDraft,
    libraryOutcomes,
    previewRevert,
    revert,
    snapshot.load,
    snapshot.loadMoreLibrary,
    snapshot.libraryPageError,
    uploader.lastResult,
    uploader.upload,
    workspaceFile,
  ]);
}
