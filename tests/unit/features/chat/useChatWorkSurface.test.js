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
  beforeEach(() => {
    mockBlocker.state = 'unblocked';
    mockBlocker.proceed.mockClear();
    mockBlocker.reset.mockClear();
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
});
