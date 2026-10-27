import { act, renderHook, waitFor } from '@testing-library/react';
import { useWorkHub } from '../../../../src/features/workspace-room/model/useWorkHub';
import * as api from '@api/chat';

const mockLoad = jest.fn();
const mockApply = jest.fn((value) => value.workspace);
let mockWorkspace;
let mockProject;
const mockRelease = jest.fn();
const mockSetFile = jest.fn();
jest.mock('../../../../src/features/workspace-room/model/useWorkSnapshot', () => ({
  useWorkSnapshot: () => ({
    hub: { workspace: mockWorkspace, library: { items: [] }, room: {} },
    load: mockLoad,
    applySnapshot: mockApply,
  }),
}));
jest.mock('../../../../src/features/workspace-room/model/useWorkspaceFile', () => ({
  EMPTY_WORK_FILE: {},
  useWorkspaceFile: () => ({
    file: { revision: '' }, releaseLease: mockRelease, setFile: mockSetFile,
  }),
}));
jest.mock('../../../../src/features/workspace-room/model/useWorkIssues', () => ({
  useWorkIssues: () => ({ items: [], status: 'ready' }),
}));
jest.mock('../../../../src/features/workspace-room/model/useWorkCollaboration', () => ({
  useWorkCollaboration: () => ({}),
}));
jest.mock('../../../../src/features/workspace-room/model/useWorkUpload', () => ({
  useWorkUpload: () => ({}),
}));
jest.mock('../../../../src/features/workspace-room/model/useDocumentForge', () => ({
  useDocumentForge: () => ({ project: mockProject }),
}));
jest.mock('../../../../src/features/workspace-room/model/workspaceSession', () => ({
  getWorkspaceActorSession: () => 'actor-test',
}));
jest.mock('@api/chat', () => ({
  activateWorkHub: jest.fn(),
  acquireWorkspaceLease: jest.fn(),
  copyLibraryFileToWorkspace: jest.fn(),
  releaseWorkspaceLease: jest.fn(),
  getWorkspaceDiff: jest.fn(),
  revertWorkspace: jest.fn(),
}));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const item = { file_id: 'owned-file', name: 'notes.md' };
function setup() {
  const notify = jest.fn();
  const view = renderHook((props) => useWorkHub({ ...props, notify }), {
    initialProps: { threadId: 'thread-old', active: true },
  });
  return { ...view, notify };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockWorkspace = { state: 'ready', revision: 'r1' };
  mockProject = undefined;
  mockLoad.mockResolvedValue(null);
  api.activateWorkHub.mockResolvedValue({ workspace: mockWorkspace });
  api.acquireWorkspaceLease.mockResolvedValue({ fence: 7 });
  api.copyLibraryFileToWorkspace.mockResolvedValue({ outcome: 'imported' });
  api.releaseWorkspaceLease.mockResolvedValue({});
  api.getWorkspaceDiff.mockResolvedValue({ diff: 'safe diff' });
  api.revertWorkspace.mockResolvedValue({});
  mockRelease.mockResolvedValue(null);
});

it('copies a Library image into the exact project using its lease and pinned revision', async () => {
  mockProject = { path: 'documents/paper', revision: 'project-r1' };
  api.copyLibraryFileToWorkspace.mockResolvedValueOnce({ outcome: 'imported', asset_path: 'figures/chart.png' });
  const view = setup();
  await act(async () => { await view.result.current.copyFromLibrary(item, { documentPath: mockProject.path }); });
  expect(api.acquireWorkspaceLease).toHaveBeenCalledWith('thread-old', 'documents/paper', { actorSession: 'actor-test' });
  expect(api.copyLibraryFileToWorkspace).toHaveBeenCalledWith('thread-old', item.file_id, 'project-r1', 7,
    { actorSession: 'actor-test', documentPath: 'documents/paper' });
  expect(view.result.current.libraryOutcomes).toEqual({ 'documents/paper/owned-file': 'imported' });
  expect(api.releaseWorkspaceLease).toHaveBeenCalledWith('thread-old', 'documents/paper', 7, { actorSession: 'actor-test' });
});

it('allows the global Library while Chat is active without enabling hidden Work actions', async () => {
  const view = setup();
  view.rerender({ threadId: 'thread-old', active: false, libraryActive: true });
  await act(async () => { await view.result.current.copyFromLibrary(item); });
  expect(api.copyLibraryFileToWorkspace).toHaveBeenCalledTimes(1);
  await act(async () => {
    await view.result.current.activateWorkspace();
    await view.result.current.previewRevert('r0');
  });
  expect(api.activateWorkHub).not.toHaveBeenCalled();
  expect(api.getWorkspaceDiff).not.toHaveBeenCalled();
  view.rerender({ threadId: 'thread-old', active: false, libraryActive: false });
  await act(async () => { await view.result.current.copyFromLibrary(item); });
  expect(api.copyLibraryFileToWorkspace).toHaveBeenCalledTimes(1);
});

it('does not advertise a project import from an old server root-copy acknowledgement', async () => {
  mockProject = { path: 'documents/paper', revision: 'project-r1' };
  const view = setup();
  await act(async () => { expect(await view.result.current.copyFromLibrary(item, { documentPath: mockProject.path })).toBe(false); });
  expect(view.result.current.libraryOutcomes).toEqual({ 'documents/paper/owned-file': 'unavailable' });
  expect(view.notify.mock.calls.some(([message]) => message.status === 'success')).toBe(false);
});

it('does not provision or copy for an unknown or mismatched document target', async () => {
  const view = setup();
  await act(async () => { await view.result.current.copyFromLibrary(item, { documentPath: 'documents/other' }); });
  expect(api.activateWorkHub).not.toHaveBeenCalled();
  expect(api.acquireWorkspaceLease).not.toHaveBeenCalled();
});

it('retires a project acquisition before dispatch if the selected project changed', async () => {
  mockProject = { path: 'documents/paper', revision: 'project-r1' };
  const pending = deferred(); api.acquireWorkspaceLease.mockReturnValueOnce(pending.promise);
  const view = setup(); let request;
  act(() => { request = view.result.current.copyFromLibrary(item, { documentPath: 'documents/paper' }); });
  await waitFor(() => expect(api.acquireWorkspaceLease).toHaveBeenCalledTimes(1));
  mockProject = { path: 'documents/other', revision: 'project-r2' };
  view.rerender({ threadId: 'thread-old', active: true });
  await act(async () => { pending.resolve({ fence: 7 }); await request; });
  expect(api.copyLibraryFileToWorkspace).not.toHaveBeenCalled();
  expect(api.releaseWorkspaceLease).toHaveBeenCalledWith('thread-old', 'documents/paper', 7, { actorSession: 'actor-test' });
  expect(view.result.current.libraryOutcomes).toEqual({});
});

it.each(['success', 'failure'])('ignores a late copy %s from another thread', async (outcome) => {
  const pending = deferred();
  api.copyLibraryFileToWorkspace.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.copyFromLibrary(item); });
  await waitFor(() => expect(api.copyLibraryFileToWorkspace).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => {
    if (outcome === 'success') pending.resolve({ outcome: 'imported' });
    else pending.reject(Object.assign(new Error('private marker'), { status: 409 }));
    await request;
  });
  expect(view.result.current.libraryOutcomes).toEqual({});
  expect(view.notify).not.toHaveBeenCalled();
  expect(mockLoad).not.toHaveBeenCalled();
  expect(api.releaseWorkspaceLease).toHaveBeenCalledWith('thread-old', 'notes.md', 7, {
    actorSession: 'actor-test',
  });
});

it('releases an obsolete acquisition without dispatching copy', async () => {
  const pending = deferred();
  api.acquireWorkspaceLease.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.copyFromLibrary(item); });
  await waitFor(() => expect(api.acquireWorkspaceLease).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => { pending.resolve({ fence: 7 }); await request; });
  expect(api.copyLibraryFileToWorkspace).not.toHaveBeenCalled();
  expect(api.releaseWorkspaceLease).toHaveBeenCalledTimes(1);
});

it('does not announce or apply an obsolete activation', async () => {
  const pending = deferred();
  api.activateWorkHub.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.activateWorkspace(); });
  await waitFor(() => expect(api.activateWorkHub).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => { pending.resolve({ workspace: mockWorkspace }); await request; });
  expect(mockApply).not.toHaveBeenCalled();
  expect(view.notify).not.toHaveBeenCalled();
});

it('rejects a retained old-thread action before dispatch', async () => {
  const view = setup();
  const old = view.result.current.copyFromLibrary;
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => { await old(item); });
  expect(api.acquireWorkspaceLease).not.toHaveBeenCalled();
  expect(view.result.current.busy).toBe('');
});

it('coalesces duplicate actions and preserves confirmed same-thread copy', async () => {
  const pending = deferred();
  api.copyLibraryFileToWorkspace.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.copyFromLibrary(item); });
  await waitFor(() => expect(api.copyLibraryFileToWorkspace).toHaveBeenCalledTimes(1));
  await act(async () => { await view.result.current.copyFromLibrary(item); });
  expect(api.acquireWorkspaceLease).toHaveBeenCalledTimes(1);
  await act(async () => { pending.resolve({ outcome: 'imported' }); await request; });
  expect(view.result.current.libraryOutcomes).toEqual({ 'owned-file': 'imported' });
  expect(view.notify).toHaveBeenCalledTimes(1);
  expect(view.result.current.busy).toBe('');
});

it('does not unlock a newer action when an old request finishes', async () => {
  const old = deferred();
  const next = deferred();
  api.activateWorkHub.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  const view = setup();
  let first;
  let second;
  act(() => { first = view.result.current.activateWorkspace(); });
  await waitFor(() => expect(api.activateWorkHub).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  act(() => { second = view.result.current.activateWorkspace(); });
  await waitFor(() => expect(api.activateWorkHub).toHaveBeenCalledTimes(2));
  await act(async () => { old.resolve({ workspace: mockWorkspace }); await first; });
  expect(view.result.current.busy).toBe('activate');
  await act(async () => { next.resolve({ workspace: mockWorkspace }); await second; });
  expect(view.result.current.busy).toBe('');
  expect(view.notify).toHaveBeenCalledTimes(1);
});

it('releases a late acquisition after unmount without notification or copy', async () => {
  const pending = deferred();
  api.acquireWorkspaceLease.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.copyFromLibrary(item); });
  await waitFor(() => expect(api.acquireWorkspaceLease).toHaveBeenCalledTimes(1));
  view.unmount();
  await act(async () => { pending.resolve({ fence: 7 }); await request; });
  expect(api.copyLibraryFileToWorkspace).not.toHaveBeenCalled();
  expect(api.releaseWorkspaceLease).toHaveBeenCalledTimes(1);
  expect(view.notify).not.toHaveBeenCalled();
});

it('does not acquire a lease after an obsolete create-and-copy activation', async () => {
  mockWorkspace = { state: 'absent', revision: '' };
  const pending = deferred();
  api.activateWorkHub.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.copyFromLibrary(item); });
  await waitFor(() => expect(api.activateWorkHub).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => {
    pending.resolve({ workspace: { state: 'ready', revision: 'r1' } });
    await request;
  });
  expect(api.acquireWorkspaceLease).not.toHaveBeenCalled();
  expect(mockApply).not.toHaveBeenCalled();
});

it('rejects actions while inactive and after unmount', async () => {
  const view = setup();
  const old = view.result.current.activateWorkspace;
  view.rerender({ threadId: 'thread-old', active: false });
  await act(async () => { await old(); });
  view.unmount();
  await old();
  expect(api.activateWorkHub).not.toHaveBeenCalled();
});

it('does not open a stale revert preview in the new chat', async () => {
  const pending = deferred();
  api.getWorkspaceDiff.mockReturnValueOnce(pending.promise);
  const view = setup();
  let request;
  act(() => { request = view.result.current.previewRevert('ref-old'); });
  await waitFor(() => expect(api.getWorkspaceDiff).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => { pending.resolve({ diff: 'old private diff' }); await request; });
  expect(view.result.current.revert).toBeNull();
  expect(view.notify).not.toHaveBeenCalled();
});

it('does not clear or release the new editor after an old revert response', async () => {
  const pending = deferred();
  api.revertWorkspace.mockReturnValueOnce(pending.promise);
  const view = setup();
  await act(async () => { await view.result.current.previewRevert('ref-old'); });
  let request;
  act(() => { request = view.result.current.applyRevert(); });
  await waitFor(() => expect(api.revertWorkspace).toHaveBeenCalledTimes(1));
  view.rerender({ threadId: 'thread-new', active: true });
  await act(async () => { pending.resolve({}); await request; });
  expect(mockRelease).not.toHaveBeenCalled();
  expect(mockSetFile).not.toHaveBeenCalled();
  expect(mockLoad).not.toHaveBeenCalled();
  expect(view.result.current.revert).toBeNull();
  expect(view.notify).not.toHaveBeenCalled();
});

it.each(['imported', 'kept'])('retains confirmed %s when background refresh fails', async (outcome) => {
  api.copyLibraryFileToWorkspace.mockResolvedValueOnce({ outcome });
  mockLoad.mockRejectedValueOnce(new Error('private read failure'));
  const view = setup();
  let accepted;
  await act(async () => { accepted = await view.result.current.copyFromLibrary(item); });
  expect(accepted).toBe(true);
  expect(view.result.current.libraryOutcomes).toEqual({ 'owned-file': outcome });
  expect(api.copyLibraryFileToWorkspace).toHaveBeenCalledTimes(1);
  expect(view.notify).toHaveBeenCalledTimes(1);
  expect(api.releaseWorkspaceLease).toHaveBeenCalledTimes(1);
});

it('does not announce ready for an incomplete activation response', async () => {
  api.activateWorkHub.mockResolvedValueOnce({ workspace: { state: 'unavailable' } });
  const view = setup();
  let accepted;
  await act(async () => { accepted = await view.result.current.activateWorkspace(); });
  expect(accepted).toBeNull();
  expect(view.notify).toHaveBeenCalledWith(expect.objectContaining({ status: 'warning' }));
  expect(view.result.current.busy).toBe('');
});
