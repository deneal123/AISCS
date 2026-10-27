import { act, renderHook } from '@testing-library/react';
import { useChatMessagePresentation } from '@features/chat/hooks/orchestration/useChatMessagePresentation';

it('does not collapse a trace while its costly decision is still pending', () => {
  jest.useFakeTimers();
  const session = { id: 'pending-offer', status: 'awaiting_confirmation', events: [] };
  const setTracePanelsExpanded = jest.fn();
  const { unmount } = renderHook(() => useChatMessagePresentation({
    messages: [], isLoading: false, scrollRef: { current: null }, showTracePanel: true,
    traceSessions: [session], activeOrLatestTraceSession: session, setTracePanelsExpanded,
    isAuthenticated: false,
  }));
  act(() => jest.advanceTimersByTime(10000));
  expect(setTracePanelsExpanded).not.toHaveBeenCalled();
  unmount();
  jest.useRealTimers();
});
