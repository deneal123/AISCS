import { act, renderHook, waitFor } from '@testing-library/react';
import { useQuestionContinuationStop } from '@features/chat/hooks/useQuestionContinuationStop';
import { cancelTask, getTaskStatus } from '@api/jobs';

jest.mock('@api/jobs', () => ({ cancelTask: jest.fn(), getTaskStatus: jest.fn() }));
const props = { scopeKey: 'account/thread/question', childId: 'child', canStart: () => true, onStart: jest.fn() };
beforeEach(() => {
  jest.resetAllMocks();
  cancelTask.mockResolvedValue({ task_id: 'child', cancelled: true });
  getTaskStatus.mockResolvedValue({ task_id: 'child', state: 'PENDING' });
});

test('Stop is explicit, deduplicated and its acknowledgement is not completion', async () => {
  const { result } = renderHook(() => useQuestionContinuationStop(props));
  expect(cancelTask).not.toHaveBeenCalled(); expect(getTaskStatus).not.toHaveBeenCalled();
  await act(async () => { await Promise.all([result.current.stop(), result.current.stop()]); });
  expect(cancelTask).toHaveBeenCalledTimes(1);
  expect(cancelTask).toHaveBeenCalledWith('child', { skipRetry: true });
  expect(result.current.requested).toBe(true); expect(result.current.closed).toBe(false);
  expect(result.current.phase).toBe('requested');
  expect(result.current.error).toContain('не подтверждена');
});

test('lost Stop acknowledgement recovers an owned terminal fact without replaying a POST', async () => {
  cancelTask.mockRejectedValue(new Error('PRIVATE ACK'));
  getTaskStatus.mockRejectedValueOnce(new Error('PRIVATE READ'));
  const { result } = renderHook(() => useQuestionContinuationStop(props));
  await act(async () => { await result.current.stop(); });
  expect(result.current.phase).toBe('unknown'); expect(result.current.error).not.toContain('PRIVATE');
  getTaskStatus.mockResolvedValue({ task_id: 'child', state: 'FAILURE' });
  await act(async () => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(result.current.closed).toBe(true));
  expect(result.current.notice).not.toMatch(/не продолжал|не списан/);
  expect(cancelTask).toHaveBeenCalledTimes(1);
});

test('unknown Stop can be explicitly retried only for the same child', async () => {
  getTaskStatus.mockRejectedValue(new Error('offline'));
  const { result } = renderHook(() => useQuestionContinuationStop(props));
  await act(async () => { await result.current.stop(); });
  await act(async () => { await result.current.refresh(); });
  expect(cancelTask).toHaveBeenCalledTimes(1);
  getTaskStatus.mockResolvedValue({ task_id: 'child', state: 'SUCCESS' });
  await act(async () => { await result.current.stop(); });
  expect(cancelTask.mock.calls.map(call => call[0])).toEqual(['child', 'child']);
  expect(result.current.notice).toContain('уже завершено');
});

test.each([{ task_id: 'other-child', state: 'FAILURE' }, { task_id: 'child', state: 'UNAVAILABLE' }])(
  'foreign or unavailable task state does not close the panel: %j', async response => {
    getTaskStatus.mockResolvedValue(response);
    const { result } = renderHook(() => useQuestionContinuationStop(props));
    await act(async () => { await result.current.stop(); });
    expect(result.current.closed).toBe(false); expect(result.current.phase).toBe('unknown');
  });

test('scope change and unmount fence a late Stop receipt and captured actions', async () => {
  let release;
  cancelTask.mockReturnValue(new Promise(resolve => { release = resolve; }));
  const { result, rerender, unmount } = renderHook(value => useQuestionContinuationStop(value), { initialProps: props });
  const captured = result.current.stop;
  let pending;
  act(() => { pending = captured(); });
  rerender({ ...props, scopeKey: 'another-account/thread/question' });
  await act(async () => { release({ task_id: 'child', cancelled: true }); await pending; });
  expect(result.current.requested).toBe(false); expect(getTaskStatus).not.toHaveBeenCalled();
  unmount(); await act(async () => { await captured(); });
  expect(cancelTask).toHaveBeenCalledTimes(1);
});

test('an in-flight financial decision owns the mutation slot', async () => {
  const { result } = renderHook(() => useQuestionContinuationStop({ ...props, canStart: () => false }));
  await act(async () => { await result.current.stop(); });
  expect(cancelTask).not.toHaveBeenCalled(); expect(result.current.requested).toBe(false);
});
