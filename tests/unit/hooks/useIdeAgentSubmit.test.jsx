import { act, renderHook } from '@testing-library/react';
import { useIdeAgentSubmit } from '@features/chat/hooks/useIdeAgentSubmit';
import { prepareIdeAgent } from '@api/ide';

jest.mock('@api/ide', () => ({ prepareIdeAgent: jest.fn() }));
const context = { repository_id: 'repo', generation: 'a'.repeat(64), blocked: false };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
beforeEach(() => jest.resetAllMocks());
it('prepares once, then sends only the opaque ticket through the existing sender', async () => {
  const pending = deferred(); prepareIdeAgent.mockReturnValue(pending.promise);
  const send = jest.fn(); const setError = jest.fn();
  const { result } = renderHook(() => useIdeAgentSubmit({ threadId: 'thread', active: true, context, send, setError }));
  let sent;
  act(() => { sent = result.current.submit('Fix'); void result.current.submit('Fix'); });
  expect(prepareIdeAgent).toHaveBeenCalledTimes(1);
  expect(send).not.toHaveBeenCalled();
  await act(async () => { pending.resolve({ target_id: '20000000-0000-0000-0000-000000000001' }); await sent; });
  expect(send).toHaveBeenCalledWith('Fix', { ideTargetId: '20000000-0000-0000-0000-000000000001', ideRepository: 'repo', routeOverride: 'general' });
  expect(setError).not.toHaveBeenCalled();
});
it('does not send after a target/surface change or Stop, and keeps errors bounded', async () => {
  const pending = deferred(); prepareIdeAgent.mockReturnValue(pending.promise);
  const send = jest.fn(); const setError = jest.fn();
  const { result, rerender } = renderHook(({ active }) => useIdeAgentSubmit({ threadId: 'thread', active, context, send, setError }), { initialProps: { active: true } });
  let sent; act(() => { sent = result.current.submit('Fix'); });
  rerender({ active: false });
  await act(async () => { pending.resolve({ target_id: '20000000-0000-0000-0000-000000000001' }); await sent; });
  expect(send).not.toHaveBeenCalled();
  expect(setError).not.toHaveBeenCalled();
  rerender({ active: true }); prepareIdeAgent.mockRejectedValue(new Error('PRIVATE'));
  await act(async () => { await result.current.submit('Fix'); });
  expect(setError.mock.calls[0][0]).not.toContain('PRIVATE');
});
