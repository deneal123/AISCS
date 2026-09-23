import { useCallback, useState } from 'react';

export function useWorkCollaboration({
  threadId,
  workspace,
  refreshIssues,
  refreshSnapshot,
  notify,
  onCancelRun,
}) {
  const [busy, setBusy] = useState('');

  const refreshCollaboration = useCallback(async () => {
    await Promise.allSettled([
      refreshIssues?.(),
      refreshSnapshot?.({ background: true }),
    ]);
  }, [refreshIssues, refreshSnapshot]);

  const createIssue = useCallback(async ({ file, title, body, startLine, endLine }) => {
    if (!threadId || !file?.path || !title.trim()) return false;
    setBusy('issue:create');
    try {
      const { createWorkspaceIssue } = await import('@api/chat');
      await createWorkspaceIssue(threadId, {
        path: file.path,
        title: title.trim(),
        body: body.trim(),
        revision: file.revision || workspace.revision,
        start_line: Number(startLine || 1),
        end_line: Number(endLine || startLine || 1),
      });
      await refreshCollaboration();
      return true;
    } catch {
      notify?.({ title: 'Не удалось добавить задачу', status: 'warning', duration: 3000 });
      return false;
    } finally {
      setBusy('');
    }
  }, [notify, refreshCollaboration, threadId, workspace.revision]);

  const updateIssue = useCallback(async (issue, status) => {
    if (!threadId) return false;
    setBusy(`issue:${issue.issue_id}`);
    try {
      const { updateWorkspaceIssue } = await import('@api/chat');
      await updateWorkspaceIssue(threadId, issue.issue_id, {
        status,
        revision: workspace.revision,
      });
      await refreshCollaboration();
      return true;
    } catch {
      notify?.({ title: 'Не удалось обновить задачу', status: 'warning', duration: 3000 });
      return false;
    } finally {
      setBusy('');
    }
  }, [notify, refreshCollaboration, threadId, workspace.revision]);

  const controlAgent = useCallback(async (action) => {
    if (!threadId) return false;
    setBusy(`control:${action}`);
    try {
      const { controlWorkspaceRun } = await import('@api/chat');
      await controlWorkspaceRun(threadId, action);
      if (action === 'cancel') await onCancelRun?.();
      await Promise.allSettled([refreshSnapshot?.({ background: true })]);
      return true;
    } catch {
      notify?.({
        title: 'Не удалось изменить состояние агента',
        status: 'warning',
        duration: 3000,
      });
      return false;
    } finally {
      setBusy('');
    }
  }, [notify, onCancelRun, refreshSnapshot, threadId]);

  return {
    busy,
    createIssue,
    updateIssue,
    controlAgent,
  };
}
