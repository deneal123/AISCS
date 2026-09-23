import { act, renderHook } from '@testing-library/react';
import { useChatThreadCommands } from '@features/chat/hooks/orchestration/useChatThreadCommands';

const createProps = () => ({
  threadId: 'thread-1',
  messages: [],
  visibleMessages: [],
  recentThreads: [],
  setRecentThreads: jest.fn(),
  currentJob: null,
  voiceText: '',
  setVoiceText: jest.fn(),
  composerRef: { current: { clearInput: jest.fn(), appendInputValue: jest.fn() } },
  navigate: jest.fn(),
  startFreshThread: jest.fn(() => 'thread-new'),
  clearMessages: jest.fn(),
  clearAttachments: jest.fn(),
  clearError: jest.fn(),
  resetTraceSessions: jest.fn(),
  setTracePanelsExpanded: jest.fn(),
  sidebarSearchActions: { setSidebarSearch: jest.fn(), setIsSidebarCollapsed: jest.fn() },
  sidebarDisclosure: { onClose: jest.fn() },
  sideEffects: { notify: jest.fn(), goToThread: jest.fn() },
  handleCancelJob: jest.fn(),
  settingsDisclosure: { onOpen: jest.fn() },
  openMemoryPanel: jest.fn(),
  setSelectedModelOverride: jest.fn(),
  requestGuardedAction: jest.fn(),
});

describe('useChatThreadCommands dirty navigation', () => {
  it('defers every new-chat side effect to the shared guard', () => {
    const props = createProps();
    const { result } = renderHook(() => useChatThreadCommands(props));

    act(() => result.current.startNewChat());
    expect(props.requestGuardedAction).toHaveBeenCalledTimes(1);
    expect(props.clearMessages).not.toHaveBeenCalled();
    expect(props.startFreshThread).not.toHaveBeenCalled();

    const guardedAction = props.requestGuardedAction.mock.calls[0][0];
    act(() => guardedAction());
    expect(props.clearMessages).toHaveBeenCalledTimes(1);
    expect(props.startFreshThread).toHaveBeenCalledTimes(1);
    expect(props.navigate).toHaveBeenCalledWith('/chat/thread-new');
  });
});
