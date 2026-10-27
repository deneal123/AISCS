import { act, renderHook } from '@testing-library/react';
import { useDocumentAssistant } from '@features/chat/hooks/useDocumentAssistant';

const anchor = { id: 'user-1', type: 'user', content: 'Правка документа' };
const session = { id: 'trace-1', anchorMessageId: anchor.id, status: 'running', events: [] };
const props = { visibleMessages: [anchor], traceSessionByAnchor: new Map([[anchor.id, session]]), activeTraceSession: session };

it('observes an anchored run without relying on trace visibility preferences', () => {
  const { result, rerender } = renderHook((value) => useDocumentAssistant(value), { initialProps: props });
  expect(result.current.tracing).toBe(false);
  rerender({ ...props, isLoading: true, showTracePanel: false });
  expect(result.current.tracing).toBe(true);
  expect(result.current.session).toBe(session);
  rerender({ ...props, isLoading: false, activeTraceSession: { ...session, status: 'done' } });
  expect(result.current.tracing).toBe(false);
});

it('never borrows a trace anchored to another project', () => {
  const { result } = renderHook(() => useDocumentAssistant({
    ...props, visibleMessages: [], isLoading: true,
  }));
  expect(result.current.session).toBeFalsy();
  expect(result.current.anchor).toBeUndefined();
});

it('does not borrow an older task result after reload or a newer user request', () => {
  const old = { id: 'old', type: 'agent', timestamp: '2026-10-24T10:00:00Z',
    metadata: { task_result: { schema_version: 2, status: 'blocked', verified: false, blocker: 'cost_unknown' } } };
  const user = { ...anchor, timestamp: '2026-10-24T10:01:00Z' };
  const { result, rerender } = renderHook(value => useDocumentAssistant(value), {
    initialProps: { ...props, visibleMessages: [user, old] },
  });
  expect(result.current.taskResult).toBeNull();
  const current = { ...old, id: 'new', timestamp: '2026-10-24T10:02:00Z' };
  rerender({ ...props, visibleMessages: [current, user, old] });
  expect(result.current.taskResult.detail).toContain('Расход ещё не подтверждён');
});

it('keeps a pending decision visible, then restores input on expiry without dispatch', () => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2026-10-15T12:00:00Z'));
  const waiting = { ...session, status: 'awaiting_confirmation', events: [{ offer: {
    mode: 'deep_research', offer_id: 'offer-1', offered_at: new Date().toISOString(), expires_in_sec: 2,
  } }] };
  const { result, unmount } = renderHook(() => useDocumentAssistant({ ...props, activeTraceSession: waiting }));
  expect(result.current.waiting).toBe(true);
  expect(result.current.tracing).toBe(true);
  act(() => { jest.advanceTimersByTime(3000); });
  expect(result.current.tracing).toBe(false);
  expect(result.current.expired).toBe(true);
  unmount();
  jest.useRealTimers();
});

it.each(['accepted', 'declined'])('a persisted %s offer is not presented as pending or expired', (status) => {
  const { result } = renderHook(() => useDocumentAssistant({ ...props, activeTraceSession: {
    ...session, status: 'awaiting_confirmation', events: [{ offer: {
      status, expired: false, offered_at: '2020-01-01T00:00:00Z', expires_in_sec: 30,
    } }],
  } }));
  expect(result.current.tracing).toBe(false);
  expect(result.current.expired).toBe(false);
});
