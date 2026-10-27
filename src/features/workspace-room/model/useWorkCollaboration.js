import { useCallback } from 'react';
import { useWorkActionOwner } from './useWorkActionOwner';

export function useWorkCollaboration({
  threadId,
  workspace,
  refreshIssues,
  refreshSnapshot,
  notify,
  onCancelRun,
  active = true,
}) {
  const { busy, begin, owns, finish } = useWorkActionOwner({ threadId, active });

  const refreshCollaboration = useCallback(async (ticket) => {
    await Promise.allSettled([
      Promise.resolve().then(() => owns(ticket) && refreshIssues?.()),
      Promise.resolve().then(() => owns(ticket) && refreshSnapshot?.({ background: true })),
    ]);
  }, [owns, refreshIssues, refreshSnapshot]);

  const createIssue = useCallback(async ({ file, title, body, startLine, endLine }) => {
    if (!threadId || !file?.path || !title.trim()) return false;
    const ticket = begin(threadId, 'issue:create');
    if (!ticket) return false;
    try {
      const { createWorkspaceIssue } = await import('@api/chat');
      if (!owns(ticket)) return false;
      await createWorkspaceIssue(threadId, {
        path: file.path,
        title: title.trim(),
        body: body.trim(),
        revision: file.revision || workspace.revision,
        start_line: Number(startLine || 1),
        end_line: Number(endLine || startLine || 1),
      });
      if (!owns(ticket)) return false;
      await refreshCollaboration(ticket);
      return owns(ticket);
    } catch {
      if (!owns(ticket)) return false;
      notify?.({ title: 'Не удалось добавить задачу', status: 'warning', duration: 3000 });
      return false;
    } finally {
      finish(ticket);
    }
  }, [begin, finish, owns, notify, refreshCollaboration, threadId, workspace.revision]);

  const updateIssue = useCallback(async (issue, status) => {
    if (!threadId || !issue?.issue_id) return false;
    const ticket = begin(threadId, `issue:${issue.issue_id}`);
    if (!ticket) return false;
    try {
      const { updateWorkspaceIssue } = await import('@api/chat');
      if (!owns(ticket)) return false;
      await updateWorkspaceIssue(threadId, issue.issue_id, {
        status,
        revision: workspace.revision,
      });
      if (!owns(ticket)) return false;
      await refreshCollaboration(ticket);
      return owns(ticket);
    } catch {
      if (!owns(ticket)) return false;
      notify?.({ title: 'Не удалось обновить задачу', status: 'warning', duration: 3000 });
      return false;
    } finally {
      finish(ticket);
    }
  }, [begin, finish, owns, notify, refreshCollaboration, threadId, workspace.revision]);

  const controlAgent = useCallback(async (action) => {
    if (!threadId) return false;
    const ticket = begin(threadId, `control:${action}`);
    if (!ticket) return false;
    try {
      const { controlWorkspaceRun } = await import('@api/chat');
      if (!owns(ticket)) return false;
      await controlWorkspaceRun(threadId, action);
      if (!owns(ticket)) return false;
      // A local projection/refresh failure cannot revoke the server acknowledgement.
      if (action === 'cancel') {
        await Promise.allSettled([Promise.resolve().then(() => owns(ticket) && onCancelRun?.())]);
      }
      await Promise.allSettled([
        Promise.resolve().then(() => owns(ticket) && refreshSnapshot?.({ background: true })),
      ]);
      return owns(ticket);
    } catch {
      if (!owns(ticket)) return false;
      notify?.({
        title: 'Не удалось изменить состояние агента',
        status: 'warning',
        duration: 3000,
      });
      return false;
    } finally {
      finish(ticket);
    }
  }, [begin, finish, owns, notify, onCancelRun, refreshSnapshot, threadId]);

  return {
    busy,
    createIssue,
    updateIssue,
    controlAgent,
  };
}
