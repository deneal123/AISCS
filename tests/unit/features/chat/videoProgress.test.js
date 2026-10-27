import { act, renderHook } from '@testing-library/react';
import { isYoutubeSource, presentVideoProgress } from '@features/chat/model/videoProgress';
import { useTraceActivity } from '@features/chat/hooks/useTraceActivity';

describe('bounded video stage presentation', () => {
  it('recognizes video pages without trusting lookalike or javascript URLs', () => {
    expect(isYoutubeSource('https://youtu.be/uTR9FdR3Ob0')).toBe(true);
    expect(isYoutubeSource('https://www.youtube.com/watch?v=uTR9FdR3Ob0')).toBe(true);
    expect(isYoutubeSource('https://youtube.com.attacker.invalid/watch')).toBe(false);
    expect(isYoutubeSource('javascript://youtube.com/watch')).toBe(false);
  });
  it('does not render unknown stages or untrusted payload', () => {
    expect(presentVideoProgress({ stage: 'private response' })).toBeNull();
    expect(presentVideoProgress({ stage: 'download', url: 'private', label: 'private' }))
      .toEqual({ label: 'Загружаю видео', stage: 'download', heartbeat: false });
  });

  it('shows chunk counts without implying a measured download percentage', () => {
    expect(presentVideoProgress({ stage: 'authoring', current: 2, total: 5 }).label)
      .toBe('Готовлю конспект · часть 2 из 5');
    expect(presentVideoProgress({ stage: 'authoring', current: 6, total: 5 }).label)
      .toBe('Готовлю конспект');
  });
});

describe('long-running trace', () => {
  beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(new Date('2026-10-03T12:00:00Z')); });
  afterEach(() => jest.useRealTimers());

  it('distinguishes silence from a confirmed failure and resets on actual progress', () => {
    const session = { id: 's', status: 'running', startedAt: new Date().toISOString(), events: [],
      progress: { label: 'Загружаю видео', updatedAt: new Date().toISOString() } };
    const { result, rerender, unmount } = renderHook(({ value }) => useTraceActivity(value),
      { initialProps: { value: session } });
    act(() => jest.advanceTimersByTime(65000));
    expect(result.current).toMatchObject({ label: 'Загружаю видео', elapsed: '1 мин 5 с', stale: true });
    rerender({ value: { ...session, progress: { ...session.progress, updatedAt: new Date().toISOString() } } });
    expect(result.current.stale).toBe(false);
    unmount();
    expect(jest.getTimerCount()).toBe(0);
  });
});
