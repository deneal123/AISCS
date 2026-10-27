import { act, renderHook } from '@testing-library/react';
import { useChatThreadRouting } from '@features/chat/hooks/orchestration/useChatThreadRouting';

describe('useChatThreadRouting', () => {
  it('replaces only a proven inaccessible current scope and preserves its workbench surface', () => {
    const navigate = jest.fn(); const startFreshThread = jest.fn(() => 'fresh');
    const { result } = renderHook(() => useChatThreadRouting({ routeThreadId: 'old', threadId: 'old', search: '?surface=pdf&profile=open', navigate, startFreshThread }));
    act(() => result.current.actions.handleUnavailableThread('stale'));
    expect(navigate).not.toHaveBeenCalled();
    act(() => result.current.actions.handleUnavailableThread('old'));
    act(() => result.current.actions.handleUnavailableThread('old'));
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith('/chat/fresh?surface=pdf', { replace: true });
  });
  it('redirects to fallback thread when route missing', () => {
    const navigate = jest.fn();
    renderHook(() => useChatThreadRouting({ routeThreadId: '', initialMessage: '', threadId: 't2', navigate }));
    expect(navigate).toHaveBeenCalledWith('/chat/t2', { replace: true });
  });

  it('preserves the selected model and surface while materializing the thread URL', () => {
    const navigate = jest.fn();
    renderHook(() => useChatThreadRouting({
      routeThreadId: '',
      initialMessage: '',
      threadId: 't2',
      search: '?model=GigaChat-3-Lightning&surface=work',
      navigate,
    }));
    expect(navigate).toHaveBeenCalledWith(
      '/chat/t2?model=GigaChat-3-Lightning&surface=work',
      { replace: true },
    );
  });
});
