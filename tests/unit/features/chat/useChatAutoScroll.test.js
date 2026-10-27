import { act, renderHook } from '@testing-library/react';
import { useChatAutoScroll } from '@features/chat/hooks/useChatAutoScroll';

describe('trace reading does not resume following on idle', () => {
  it('preserves reading during non-streaming trace updates', () => {
    const node = document.createElement('div');
    Object.defineProperties(node, { scrollHeight: { value: 2000 }, clientHeight: { value: 500 } });
    const scrollRef = { current: node };
    const { rerender, unmount } = renderHook(({ signal }) => useChatAutoScroll({
      scrollRef, contentSignal: signal, isStreaming: false,
    }), { initialProps: { signal: '1:agent:10' } });
    node.scrollTop = 200;
    act(() => node.dispatchEvent(new Event('pointerdown')));
    rerender({ signal: '1:agent:300' });
    expect(node.scrollTop).toBe(200);
    unmount();
  });

  it('interrupts a pending smooth scroll when the reader takes control', () => {
    jest.useFakeTimers();
    const node = document.createElement('div');
    node.scrollTo = jest.fn();
    Object.defineProperties(node, { scrollHeight: { value: 2000 }, clientHeight: { value: 500 } });
    const scrollRef = { current: node };
    const { result, unmount } = renderHook(() => useChatAutoScroll({
      scrollRef, contentSignal: '1:agent:10', isStreaming: true,
    }));
    act(() => result.current.scrollToBottom());
    node.scrollTop = 200;
    act(() => {
      node.dispatchEvent(new Event('wheel'));
      result.current.handleScroll({ currentTarget: node });
    });
    expect(result.current.atBottom).toBe(false);
    expect(node.scrollTo).toHaveBeenLastCalledWith({ top: 200, behavior: 'instant' });
    unmount();
    jest.useRealTimers();
  });

  it('keeps the user position through timer ticks and growing trace, then follows an explicit new message', () => {
    jest.useFakeTimers();
    const node = document.createElement('div');
    Object.defineProperties(node, { scrollHeight: { value: 2000 }, clientHeight: { value: 500 } });
    const scrollRef = { current: node };
    const { result, rerender, unmount } = renderHook(({ signal }) => useChatAutoScroll({
      scrollRef, contentSignal: signal, isStreaming: true,
    }), { initialProps: { signal: '1:user:10' } });
    act(() => {
      node.dispatchEvent(new Event('wheel'));
      node.scrollTop = 200;
      result.current.handleScroll({ currentTarget: node });
    });
    act(() => jest.advanceTimersByTime(10000));
    rerender({ signal: '1:agent:300' });
    expect(node.scrollTop).toBe(200);
    rerender({ signal: '2:user:12' });
    expect(node.scrollTop).toBe(2000);
    unmount();
    jest.useRealTimers();
  });
});
