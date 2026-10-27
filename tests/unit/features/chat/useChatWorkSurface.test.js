import { act, renderHook } from '@testing-library/react';
import { useChatWorkSurface } from '@features/chat/hooks/orchestration/useChatWorkSurface';

const mockBlocker = {
  state: 'unblocked',
  proceed: jest.fn(),
  reset: jest.fn(),
};

jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useBlocker: jest.fn(() => mockBlocker),
}));

describe('useChatWorkSurface', () => {
  it('keeps the PDF dirty owner when a clean IDE lifecycle mounts and unregisters', async () => {
    const action = jest.fn(); const pdf = jest.fn().mockResolvedValue(true); const ide = jest.fn().mockReturnValue(true);
    const { result } = renderHook(() => useChatWorkSurface({ location: { pathname: '/chat/thread-1', search: '?surface=pdf' }, navigate: jest.fn() }));
    let unregister;
    act(() => { result.current.registerWorkspaceLifecycle({ abandon: pdf }); result.current.setWorkspaceDirty(true); });
    act(() => { unregister = result.current.registerWorkspaceLifecycle({ abandon: ide }, 'ide'); result.current.setWorkspaceDirty(false, 'ide'); });
    act(() => { unregister(); result.current.requestGuardedAction(action); });
    expect(action).not.toHaveBeenCalled();
    await act(async () => result.current.confirmSurfaceChange());
    expect(pdf).toHaveBeenCalledTimes(1);
    expect(ide).not.toHaveBeenCalled();
    expect(action).toHaveBeenCalledTimes(1);
  });
  it('consumes the account profile flag without losing the thread, IDE or other query state', () => {
    const navigate = jest.fn();
    const profileDisclosure = { onOpen: jest.fn() };
    renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work&profile=open&keep=1' },
      navigate, profileDisclosure,
    }));
    expect(profileDisclosure.onOpen).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith('/chat/thread-1?surface=work&keep=1', { replace: true });
  });
  it('opens a saved document in PDF without retargeting IDE and preserves query state', () => {
    const navigate = jest.fn();
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work&keep=1' }, navigate,
    }));
    act(() => result.current.openPdfSurface());
    expect(navigate).toHaveBeenCalledWith('/chat/thread-1?surface=pdf&keep=1');
  });
  beforeEach(() => {
    mockBlocker.state = 'unblocked';
    mockBlocker.proceed.mockClear();
    mockBlocker.reset.mockClear();
  });

  it('does not navigate or clear dirty protection when cleanup rejects an obsolete owner', async () => {
    const action = jest.fn();
    const abandon = jest.fn().mockResolvedValue(false);
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' }, navigate: jest.fn(),
    }));
    act(() => result.current.registerWorkspaceLifecycle({ abandon }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(action));
    await act(async () => result.current.confirmSurfaceChange());
    expect(action).not.toHaveBeenCalled();
    expect(result.current.navigationPending).toBe(true);
    expect(mockBlocker.proceed).not.toHaveBeenCalled();
  });

  it('late cleanup after unmount cannot execute its pending navigation', async () => {
    let release;
    const pending = new Promise((resolve) => { release = resolve; });
    const action = jest.fn();
    const { result, unmount } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' }, navigate: jest.fn(),
    }));
    act(() => result.current.registerWorkspaceLifecycle({ abandon: () => pending }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(action));
    let confirming;
    act(() => { confirming = result.current.confirmSurfaceChange(); });
    unmount();
    await act(async () => { release(true); await confirming; });
    expect(action).not.toHaveBeenCalled();
  });

  it.each(['another-thread', 'unmounted'])('captured navigation request cannot dispatch when %s', (scope) => {
    const action = jest.fn();
    const { result, rerender, unmount } = renderHook(({ pathname }) => useChatWorkSurface({
      location: { pathname, search: '?surface=work' }, navigate: jest.fn(),
    }), { initialProps: { pathname: '/chat/thread-1' } });
    const captured = result.current.requestGuardedAction;
    if (scope === 'unmounted') unmount();
    else rerender({ pathname: '/chat/thread-2' });
    let accepted;
    act(() => { accepted = captured(action); });
    expect(action).not.toHaveBeenCalled();
    expect(accepted).toBe(false);
  });

  it('a retained same-scope request checks current dirty state rather than its old render', () => {
    const action = jest.fn();
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' }, navigate: jest.fn(),
    }));
    const captured = result.current.requestGuardedAction;
    act(() => result.current.setWorkspaceDirty(true));
    act(() => captured(action));
    expect(action).not.toHaveBeenCalled();
    expect(result.current.navigationPending).toBe(true);
  });

  it('returning to the same route never re-admits an earlier owner callback', () => {
    const action = jest.fn();
    const { result, rerender } = renderHook(({ pathname }) => useChatWorkSurface({
      location: { pathname, search: '?surface=work' }, navigate: jest.fn(),
    }), { initialProps: { pathname: '/chat/thread-1' } });
    const captured = result.current.requestGuardedAction;
    rerender({ pathname: '/chat/thread-2' });
    rerender({ pathname: '/chat/thread-1' });
    act(() => expect(captured(action)).toBe(false));
    expect(action).not.toHaveBeenCalled();
  });

  it('old cleanup cannot execute or unlock a newer confirmation after scope change', async () => {
    let releaseOld;
    let releaseNew;
    const oldPending = new Promise((resolve) => { releaseOld = resolve; });
    const newPending = new Promise((resolve) => { releaseNew = resolve; });
    const oldAction = jest.fn();
    const newAction = jest.fn();
    const newAbandon = jest.fn(() => newPending);
    const { result, rerender } = renderHook(({ pathname }) => useChatWorkSurface({
      location: { pathname, search: '?surface=work' }, navigate: jest.fn(),
    }), { initialProps: { pathname: '/chat/thread-1' } });
    act(() => result.current.registerWorkspaceLifecycle({ abandon: () => oldPending }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(oldAction));
    let oldConfirm;
    act(() => { oldConfirm = result.current.confirmSurfaceChange(); });
    rerender({ pathname: '/chat/thread-2' });
    act(() => result.current.registerWorkspaceLifecycle({ abandon: newAbandon }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(newAction));
    let newConfirm;
    act(() => { newConfirm = result.current.confirmSurfaceChange(); });
    await act(async () => { releaseOld(true); await oldConfirm; });
    await act(async () => result.current.confirmSurfaceChange());
    expect(oldAction).not.toHaveBeenCalled();
    expect(newAction).not.toHaveBeenCalled();
    expect(newAbandon).toHaveBeenCalledTimes(1);
    await act(async () => { releaseNew(true); await newConfirm; });
    expect(newAction).toHaveBeenCalledTimes(1);
  });

  it('cancelling an in-flight cleanup prevents its later target action', async () => {
    let release;
    const pending = new Promise((resolve) => { release = resolve; });
    const action = jest.fn();
    const duplicate = jest.fn();
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' }, navigate: jest.fn(),
    }));
    act(() => result.current.registerWorkspaceLifecycle({ abandon: () => pending }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(action));
    let confirming;
    act(() => { confirming = result.current.confirmSurfaceChange(); });
    act(() => expect(result.current.requestGuardedAction(duplicate)).toBe(false));
    act(() => result.current.cancelSurfaceChange());
    await act(async () => { release(true); await confirming; });
    expect(action).not.toHaveBeenCalled();
    expect(duplicate).not.toHaveBeenCalled();
  });

  it('opens Work through URL navigation without activating a sandbox', () => {
    const navigate = jest.fn();
    const location = { pathname: '/chat/thread-1', search: '' };
    const { result } = renderHook(() => useChatWorkSurface({ location, navigate }));

    act(() => result.current.openWorkSurface());

    expect(navigate).toHaveBeenCalledWith('/chat/thread-1?surface=work');
    expect(result.current.activeSurface).toBe('chat');
  });

  it('holds a dirty Work-to-Chat transition until explicit confirmation', () => {
    const navigate = jest.fn();
    const location = { pathname: '/chat/thread-1', search: '?surface=work&profile=open' };
    const { result } = renderHook(() => useChatWorkSurface({ location, navigate }));

    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.changeSurface('chat'));

    expect(navigate).not.toHaveBeenCalled();
    expect(result.current.pendingSurface).toBe('chat');

    return act(async () => {
      await result.current.confirmSurfaceChange();
      expect(navigate).toHaveBeenCalledWith('/chat/thread-1?profile=open');
    });
  });

  it('can dismiss a pending dirty transition without changing the URL', () => {
    const navigate = jest.fn();
    const location = { pathname: '/chat/thread-1', search: '?surface=work' };
    const { result } = renderHook(() => useChatWorkSurface({ location, navigate }));

    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.changeSurface('chat'));
    act(() => result.current.cancelSurfaceChange());

    expect(result.current.pendingSurface).toBe('');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('runs a guarded action once after discarding the draft and releasing its lifecycle', async () => {
    const action = jest.fn();
    const abandon = jest.fn(() => Promise.resolve());
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' },
      navigate: jest.fn(),
    }));
    act(() => result.current.registerWorkspaceLifecycle({ abandon }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(action));

    expect(action).not.toHaveBeenCalled();
    expect(result.current.navigationPending).toBe(true);
    await act(async () => result.current.confirmSurfaceChange());

    expect(abandon).toHaveBeenCalledTimes(1);
    expect(action).toHaveBeenCalledTimes(1);
  });

  it('installs beforeunload only while a workspace draft is dirty', () => {
    const add = jest.spyOn(window, 'addEventListener');
    const remove = jest.spyOn(window, 'removeEventListener');
    const { result, unmount } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' },
      navigate: jest.fn(),
    }));

    act(() => result.current.setWorkspaceDirty(true));
    expect(add).toHaveBeenCalledWith('beforeunload', expect.any(Function));
    unmount();
    expect(remove).toHaveBeenCalledWith('beforeunload', expect.any(Function));
    add.mockRestore();
    remove.mockRestore();
  });

  it('delegates cancellation focus to the dialog final-focus ref without premature focus calls', () => {
    const editor = document.createElement('textarea');
    document.body.append(editor);
    const focus = jest.spyOn(editor, 'focus');
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' },
      navigate: jest.fn(),
    }));
    act(() => result.current.registerWorkspaceLifecycle({ editorRef: { current: editor } }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.changeSurface('chat'));
    act(() => result.current.cancelSurfaceChange());
    expect(focus).not.toHaveBeenCalled();
    expect(result.current.navigationFinalFocusRef.current).toBe(editor);
    expect(result.current.navigationPending).toBe(false);
    editor.remove();
    focus.mockRestore();
  });

  it('falls back to the connected initiating control when there is no editor', () => {
    const button = document.createElement('button');
    document.body.append(button);
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' },
      navigate: jest.fn(),
    }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.requestGuardedAction(jest.fn(), { returnFocus: button }));
    act(() => result.current.cancelSurfaceChange());
    expect(result.current.navigationFinalFocusRef.current).toBe(button);
    button.remove();
  });

  it('does not restore the old editor after confirmed discard', async () => {
    const editor = document.createElement('textarea');
    document.body.append(editor);
    const { result } = renderHook(() => useChatWorkSurface({
      location: { pathname: '/chat/thread-1', search: '?surface=work' },
      navigate: jest.fn(),
    }));
    act(() => result.current.registerWorkspaceLifecycle({ editorRef: { current: editor } }));
    act(() => result.current.setWorkspaceDirty(true));
    act(() => result.current.changeSurface('chat'));
    act(() => result.current.cancelSurfaceChange());
    expect(result.current.navigationFinalFocusRef.current).toBe(editor);
    act(() => result.current.changeSurface('chat'));
    await act(async () => result.current.confirmSurfaceChange());
    expect(result.current.navigationFinalFocusRef.current).toBeNull();
    editor.remove();
  });
});
