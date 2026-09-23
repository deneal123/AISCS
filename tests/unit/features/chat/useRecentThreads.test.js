import { act, renderHook } from '@testing-library/react';
import { deleteChatThread } from '@api/chat';
import { useRecentThreads } from '@features/chat/hooks/useRecentThreads';

jest.mock('@api/chat', () => ({
  deleteChatThread: jest.fn(() => Promise.resolve()),
}));

describe('useRecentThreads dirty navigation', () => {
  beforeEach(() => deleteChatThread.mockClear());

  it('guards deletion of the active thread before the destructive request', async () => {
    const requestGuardedAction = jest.fn();
    const navigate = jest.fn();
    const setMessages = jest.fn();
    const { result } = renderHook(() => useRecentThreads({
      navigate,
      resolveSessionUserId: () => 'user-1',
      threadId: 'thread-1',
      setMessages,
      isAuthenticated: false,
      requestGuardedAction,
    }));
    const event = { preventDefault: jest.fn(), stopPropagation: jest.fn(), currentTarget: {} };

    act(() => result.current.handleDeleteThread({ thread_id: 'thread-1' }, event));
    expect(requestGuardedAction).toHaveBeenCalledTimes(1);
    expect(deleteChatThread).not.toHaveBeenCalled();

    await act(async () => requestGuardedAction.mock.calls[0][0]());
    expect(deleteChatThread).toHaveBeenCalledWith('thread-1', 'user-1');
    expect(setMessages).toHaveBeenCalledWith([]);
    expect(navigate).toHaveBeenCalledWith('/chat');
  });
});
