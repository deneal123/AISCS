import { act, renderHook } from '@testing-library/react';
import { createWorkspaceIssue, updateWorkspaceIssue, controlWorkspaceRun } from '@api/chat';
import { useWorkCollaboration } from '@features/workspace-room/model/useWorkCollaboration';

jest.mock('@api/chat', () => ({
  createWorkspaceIssue: jest.fn(() => Promise.resolve({ issue_id: 'issue-1' })),
  updateWorkspaceIssue: jest.fn(() => Promise.resolve({})),
  controlWorkspaceRun: jest.fn(() => Promise.resolve({})),
}));

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

const input = {
  file: { path: 'note.txt', revision: 'r1' }, title: 'Проверить', body: '',
  startLine: 1, endLine: 1,
};

const actions = [
  ['create', createWorkspaceIssue, (hook) => hook.createIssue(input)],
  ['update', updateWorkspaceIssue, (hook) => hook.updateIssue({ issue_id: 'issue-1' }, 'resolved')],
  ['cancel', controlWorkspaceRun, (hook) => hook.controlAgent('cancel')],
];

describe('useWorkCollaboration', () => {
  beforeEach(() => jest.clearAllMocks());

  it.each(actions)('ignores late %s success after thread change', async (_name, api, invoke) => {
    const pending = deferred();
    api.mockReturnValueOnce(pending.promise);
    const refreshIssues = jest.fn();
    const refreshSnapshot = jest.fn();
    const notify = jest.fn();
    const onCancelRun = jest.fn();
    const { result, rerender } = renderHook(({ threadId }) => useWorkCollaboration({
      threadId, workspace: { revision: 'r1' }, refreshIssues, refreshSnapshot, notify, onCancelRun,
    }), { initialProps: { threadId: 'old' } });
    let operation;
    await act(async () => { operation = invoke(result.current); });
    rerender({ threadId: 'new' });
    let outcome;
    await act(async () => { pending.resolve({}); outcome = await operation; });
    expect(outcome).toBe(false);
    expect(refreshIssues).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(onCancelRun).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it('rejects duplicate issue creation before dispatch', async () => {
    const pending = deferred();
    createWorkspaceIssue.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useWorkCollaboration({
      threadId: 'thread', workspace: { revision: 'r1' },
    }));
    let first;
    let duplicate;
    await act(async () => {
      first = result.current.createIssue(input);
      duplicate = await result.current.createIssue(input);
    });
    expect(duplicate).toBe(false);
    expect(createWorkspaceIssue).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve({}); await first; });
  });

  it.each(actions)('ignores late %s failure after unmount', async (_name, api, invoke) => {
    const pending = deferred();
    api.mockReturnValueOnce(pending.promise);
    const notify = jest.fn();
    const refreshSnapshot = jest.fn();
    const { result, unmount } = renderHook(() => useWorkCollaboration({
      threadId: 'thread', workspace: { revision: 'r1' }, notify, refreshSnapshot,
    }));
    let operation;
    await act(async () => { operation = invoke(result.current); });
    unmount();
    pending.reject(new Error('private-response-marker'));
    expect(await operation).toBe(false);
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
  });

  it.each(actions)('rejects captured %s callbacks from another thread or hidden Work',
    async (_name, api, invoke) => {
      const { result, rerender } = renderHook((props) => useWorkCollaboration({
        ...props, workspace: { revision: 'r1' },
      }), { initialProps: { threadId: 'old', active: true } });
      const previous = result.current;
      rerender({ threadId: 'new', active: true });
      await act(async () => { expect(await invoke(previous)).toBe(false); });
      rerender({ threadId: 'new', active: false });
      await act(async () => { expect(await invoke(result.current)).toBe(false); });
      expect(api).not.toHaveBeenCalled();
    });

  it('old completion does not clear the new thread operation', async () => {
    const old = deferred();
    const current = deferred();
    createWorkspaceIssue.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const { result, rerender } = renderHook(({ threadId }) => useWorkCollaboration({
      threadId, workspace: { revision: 'r1' },
    }), { initialProps: { threadId: 'old' } });
    let first;
    let second;
    await act(async () => { first = result.current.createIssue(input); });
    rerender({ threadId: 'new' });
    await act(async () => { second = result.current.createIssue(input); });
    await act(async () => { old.resolve({}); expect(await first).toBe(false); });
    expect(result.current.busy).toBe('issue:create');
    await act(async () => { current.resolve({}); expect(await second).toBe(true); });
    expect(result.current.busy).toBe('');
  });

  it('keeps confirmed cancellation successful when local callbacks throw', async () => {
    const { result } = renderHook(() => useWorkCollaboration({
      threadId: 'thread', workspace: { revision: 'r1' },
      onCancelRun: () => { throw new Error('private-response-marker'); },
      refreshSnapshot: () => { throw new Error('private-response-marker'); },
    }));
    await act(async () => { expect(await result.current.controlAgent('cancel')).toBe(true); });
    expect(controlWorkspaceRun).toHaveBeenCalledTimes(1);
  });

  it('keeps confirmed issue creation successful when refresh throws synchronously', async () => {
    const refreshSnapshot = jest.fn();
    const { result } = renderHook(() => useWorkCollaboration({
      threadId: 'thread', workspace: { revision: 'r1' }, refreshSnapshot,
      refreshIssues: () => { throw new Error('private-response-marker'); },
    }));
    await act(async () => { expect(await result.current.createIssue(input)).toBe(true); });
    expect(refreshSnapshot).toHaveBeenCalledWith({ background: true });
  });

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
