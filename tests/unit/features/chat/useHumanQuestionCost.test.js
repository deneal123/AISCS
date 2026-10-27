import { act, renderHook, waitFor } from '@testing-library/react';
import { useHumanQuestionCost } from '@features/chat/hooks/useHumanQuestionCost';
import { parseHumanQuestionCost } from '@features/chat/model/humanQuestionCost';
import { decideHumanQuestionCost, readHumanQuestionCost } from '@api/humanQuestions';
import { cancelTask, getTaskStatus } from '@api/jobs';

jest.mock('@api/humanQuestions', () => ({ decideHumanQuestionCost: jest.fn(), readHumanQuestionCost: jest.fn() }));
jest.mock('@api/jobs', () => ({ cancelTask: jest.fn(), getTaskStatus: jest.fn() }));
const OFFER = '88888888-8888-4888-8888-888888888888';
function fixture() {
  const view = { offer_id: OFFER, state: 'pending', estimated_credits: 5000, expires_at: new Date(Date.now() + 30000).toISOString() };
  readHumanQuestionCost.mockResolvedValue(view);
  decideHumanQuestionCost.mockResolvedValue({ ...view, state: 'accepted' });
  const props = { threadId: 'thread', scopeKey: 'account/thread/question', active: true,
    question: { state: 'accepted', resume_job_id: 'child', question_id: 'question', source_job_id: 'source' } };
  return { view, props };
}
beforeEach(() => jest.clearAllMocks());

test('Stop after an unknown paid decision blocks payment and checks only the same owned child', async () => {
  const f = fixture();
  decideHumanQuestionCost.mockRejectedValueOnce(new Error('unknown accept'));
  cancelTask.mockRejectedValueOnce(new Error('unknown Stop'));
  getTaskStatus.mockRejectedValueOnce(new Error('offline'));
  const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  const staleAccept = result.current.decide;
  await act(async () => { await result.current.decide('accept'); });
  await act(async () => { await result.current.stop.stop(); });
  expect(result.current.phase).toBe('cost_stop_unknown');
  expect(result.current.ready).toBe(false); expect(result.current.closed).toBe(false);
  await act(async () => { await staleAccept('accept'); });
  expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
  readHumanQuestionCost.mockResolvedValue({ ...f.view, state: 'accepted' });
  getTaskStatus.mockResolvedValue({ task_id: 'child', state: 'FAILURE' });
  await act(async () => { await result.current.refresh(); });
  expect(result.current.phase).toBe('cost_stopped'); expect(result.current.closed).toBe(true);
  expect(result.current.ready).toBe(false); expect(cancelTask).toHaveBeenCalledTimes(1);
  expect(readHumanQuestionCost).toHaveBeenCalledTimes(1);
});

test('a stalled quote GET cannot block Stop or overwrite its terminal result later', async () => {
  const f = fixture(); let release;
  readHumanQuestionCost.mockReturnValue(new Promise(resolve => { release = resolve; }));
  cancelTask.mockResolvedValue({ task_id: 'child', cancelled: true });
  getTaskStatus.mockResolvedValue({ task_id: 'child', state: 'FAILURE' });
  const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(readHumanQuestionCost).toHaveBeenCalledTimes(1));
  await act(async () => { await result.current.stop.stop(); });
  expect(result.current.phase).toBe('cost_stopped');
  await act(async () => { release({ ...f.view, state: 'accepted' }); });
  expect(result.current.phase).toBe('cost_stopped'); expect(result.current.ready).toBe(false);
  expect(decideHumanQuestionCost).not.toHaveBeenCalled();
});

test('closed price projection rejects authority, unsafe amounts and ambiguous expiry', () => {
  const { view } = fixture();
  expect(parseHumanQuestionCost(view)).toEqual(view);
  for (const delta of [{ binding: 'private' }, { estimated_credits: '5000' }, { estimated_credits: -1 },
    { estimated_credits: Number.MAX_SAFE_INTEGER + 1 }, { expires_at: '2026-10-19' }, { state: 'processing' }]) {
    expect(() => parseHumanQuestionCost({ ...view, ...delta })).toThrow();
  }
});

test('reading a quote does not approve it, and double submit is one explicit decision', async () => {
  const f = fixture(); const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  expect(result.current.ready).toBe(false); expect(decideHumanQuestionCost).not.toHaveBeenCalled();
  await act(async () => { await Promise.all([result.current.decide('accept'), result.current.decide('accept')]); });
  expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
  expect(decideHumanQuestionCost).toHaveBeenCalledWith('thread', f.props.question, { offer_id: OFFER, decision: 'accept' });
  expect(result.current.ready).toBe(true);
});

test('lost acceptance acknowledgement is reconciled by GET without another mutation', async () => {
  const f = fixture(); decideHumanQuestionCost.mockRejectedValueOnce(new Error('PRIVATE'));
  const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  await act(async () => { await result.current.decide('accept'); });
  expect(result.current.phase).toBe('cost_unknown'); expect(result.current.ready).toBe(false);
  expect(result.current.error).not.toContain('PRIVATE');
  await act(async () => { await result.current.decide('decline'); });
  expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
  readHumanQuestionCost.mockResolvedValue({ ...f.view, state: 'accepted' });
  await act(async () => { await result.current.refresh(); });
  expect(result.current.ready).toBe(true); expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
});

test('a pending result after uncertainty can retry only the exact original decision', async () => {
  const f = fixture(); decideHumanQuestionCost.mockRejectedValueOnce(new Error('unknown'));
  const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  await act(async () => { await result.current.decide('accept'); await result.current.refresh(); });
  expect(result.current.retry).toBe('accept');
  await act(async () => { await result.current.decide('decline'); });
  expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
  await act(async () => { await result.current.decide('accept'); });
  expect(decideHumanQuestionCost.mock.calls[0][2]).toEqual(decideHumanQuestionCost.mock.calls[1][2]);
  expect(result.current.ready).toBe(true);
});

test('expired quotes refresh explicitly but never auto-accept the new estimate', async () => {
  const f = fixture(); readHumanQuestionCost.mockResolvedValue({ ...f.view, state: 'expired' });
  const next = { ...f.view, offer_id: '99999999-9999-4999-8999-999999999999', estimated_credits: 6000 };
  decideHumanQuestionCost.mockResolvedValue(next);
  const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_expired'));
  await act(async () => { await result.current.decide('accept'); });
  expect(decideHumanQuestionCost).not.toHaveBeenCalled();
  await act(async () => { await result.current.decide('refresh'); });
  expect(result.current.view).toEqual(next); expect(result.current.retry).toBeNull();
  expect(result.current.ready).toBe(false); expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
});

test('another account cannot receive an old amount or a late approval', async () => {
  const f = fixture(); let release;
  decideHumanQuestionCost.mockReturnValue(new Promise(resolve => { release = resolve; }));
  const { result, rerender } = renderHook(props => useHumanQuestionCost(props), { initialProps: f.props });
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  let pending; act(() => { pending = result.current.decide('accept'); });
  readHumanQuestionCost.mockRejectedValue(new Error('foreign-owner'));
  rerender({ ...f.props, scopeKey: 'other-account/thread/question' });
  await waitFor(() => expect(result.current.phase).toBe('cost_unavailable'));
  await act(async () => { release({ ...f.view, state: 'accepted' }); await pending; });
  expect(result.current.view).toBeNull(); expect(result.current.ready).toBe(false);
});

test('captured reads and decisions are inactive after unmount', async () => {
  const f = fixture(); const { result, unmount } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  const old = result.current; unmount();
  readHumanQuestionCost.mockClear();
  await act(async () => { await old.refresh(); await old.decide('accept'); });
  expect(readHumanQuestionCost).not.toHaveBeenCalled(); expect(decideHumanQuestionCost).not.toHaveBeenCalled();
});

test('a definitive project conflict still allows declining the pending continuation', async () => {
  const f = fixture();
  decideHumanQuestionCost.mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: 'human_question_binding_changed' } } } });
  const { result } = renderHook(() => useHumanQuestionCost(f.props));
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  await act(async () => { await result.current.decide('accept'); });
  expect(result.current.phase).toBe('cost_blocked'); expect(result.current.retry).toBeNull();
  await act(async () => { await result.current.decide('accept'); });
  expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
  decideHumanQuestionCost.mockResolvedValue({ ...f.view, state: 'declined' });
  await act(async () => { await result.current.decide('decline'); });
  expect(result.current.closed).toBe(true); expect(result.current.ready).toBe(false);
});
