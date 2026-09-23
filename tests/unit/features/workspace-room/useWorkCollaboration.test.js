import { act, renderHook } from '@testing-library/react';
import { createWorkspaceIssue } from '@api/chat';
import { useWorkCollaboration } from '@features/workspace-room/model/useWorkCollaboration';

jest.mock('@api/chat', () => ({
  createWorkspaceIssue: jest.fn(() => Promise.resolve({ issue_id: 'issue-1' })),
}));

describe('useWorkCollaboration', () => {
  it('keeps a confirmed mutation successful when independent refreshes fail', async () => {
    const refreshIssues = jest.fn(() => Promise.reject(new Error('issues unavailable')));
    const refreshSnapshot = jest.fn(() => Promise.reject(new Error('snapshot unavailable')));
    const { result } = renderHook(() => useWorkCollaboration({
      threadId: 'thread-1',
      workspace: { state: 'ready', revision: 'r1' },
      refreshIssues,
      refreshSnapshot,
      notify: jest.fn(),
    }));

    let saved;
    await act(async () => {
      saved = await result.current.createIssue({
        file: { path: 'note.txt', revision: 'r1' },
        title: 'Проверить',
        body: '',
        startLine: 1,
        endLine: 1,
      });
    });

    expect(saved).toBe(true);
    expect(createWorkspaceIssue).toHaveBeenCalledTimes(1);
    expect(refreshIssues).toHaveBeenCalledTimes(1);
    expect(refreshSnapshot).toHaveBeenCalledWith({ background: true });
  });
});
