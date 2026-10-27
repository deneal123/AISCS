import { act, renderHook, waitFor } from '@testing-library/react';
import { useHumanQuestion } from '@features/chat/hooks/useHumanQuestion';
import { answerHumanQuestion, cancelHumanQuestion, readHumanQuestion, readHumanQuestionCost, decideHumanQuestionCost } from '@api/humanQuestions';
import { getTaskStatus } from '@api/jobs';

jest.mock('@api/humanQuestions', () => ({ answerHumanQuestion: jest.fn(), cancelHumanQuestion: jest.fn(), readHumanQuestion: jest.fn(), readHumanQuestionCost: jest.fn(), decideHumanQuestionCost: jest.fn() }));
jest.mock('@api/jobs', () => ({ getTaskStatus: jest.fn() }));

const CHILD = '44444444-4444-4444-8444-444444444444';
function fixture() {
  const question = { question_id: '11111111-1111-4111-8111-111111111111', source_job_id: '22222222-2222-4222-8222-222222222222',
    project_id: '33333333-3333-4333-8333-333333333333', surface: 'ide', prompt: 'Какую структуру создать?',
    choices: [{ id: 'small', label: 'Минимальная' }, { id: 'full', label: 'Полная' }], state: 'pending',
    expires_at: new Date(Date.now() + 60000).toISOString(), resume_job_id: null };
  const accepted = { ...question, state: 'accepted', resume_job_id: CHILD };
  readHumanQuestionCost.mockResolvedValue({ offer_id: '88888888-8888-4888-8888-888888888888', state: 'not_required', estimated_credits: 1, expires_at: question.expires_at });
  readHumanQuestion.mockResolvedValue(question); answerHumanQuestion.mockResolvedValue(accepted);
  cancelHumanQuestion.mockResolvedValue({ ...question, state: 'cancelled' });
  getTaskStatus.mockResolvedValue({ task_id: CHILD, state: 'PENDING' });
  const props = { threadId: 'owned-thread', accountId: 'owned-account', surface: 'ide', active: true,
    messages: [{ type: 'agent', metadata: { human_question: question } }],
    context: { repository_id: question.project_id, generation: 'a'.repeat(64) }, onAccepted: jest.fn(), onSettled: jest.fn() };
  return { question, accepted, props };
}
beforeEach(() => jest.clearAllMocks());

test('passive read never submits; explicit answer uses one intent and the exact selected target', async () => {
  const f = fixture(); const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(result.current.phase).toBe('pending'));
  expect(answerHumanQuestion).not.toHaveBeenCalled();
  act(() => result.current.setChoice('small'));
  await act(async () => { await Promise.all([result.current.submit(), result.current.submit()]); });
  expect(answerHumanQuestion).toHaveBeenCalledTimes(1);
  const payload = answerHumanQuestion.mock.calls[0][2];
  expect(payload).toMatchObject({ answer: { choice_id: 'small', text: null }, ide_context: f.props.context, surface: 'ide' });
  expect(payload.intent_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(f.props.onAccepted).toHaveBeenCalledTimes(1);
  expect(result.current.blocking).toBe(false);
});

test('unknown completion retains and locks the answer; explicit retry sends the same intent and bytes', async () => {
  const f = fixture(); answerHumanQuestion.mockRejectedValueOnce(new Error('PRIVATE-TRANSPORT'));
  const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(result.current.phase).toBe('pending'));
  act(() => result.current.setText('Свой\nответ'));
  await act(async () => { await result.current.submit(); });
  const payload = answerHumanQuestion.mock.calls[0][2];
  expect(result.current.phase).toBe('unknown'); expect(result.current.locked).toBe(true);
  act(() => result.current.setText('Другой ответ'));
  expect(result.current.draft.text).toBe('Свой\nответ');
  expect(result.current.error).not.toContain('PRIVATE');
  await act(async () => { await result.current.refresh(); });
  expect(answerHumanQuestion).toHaveBeenCalledTimes(1);
  await act(async () => { await result.current.submit(); });
  expect(answerHumanQuestion.mock.calls[1][2]).toEqual(payload);
  expect(f.props.onAccepted).toHaveBeenCalledTimes(1);
});

test('reload recovers an accepted child by reads, and cancellation racing with answer follows that child', async () => {
  const f = fixture(); readHumanQuestion.mockResolvedValue(f.accepted);
  getTaskStatus.mockResolvedValue({ task_id: CHILD, state: 'SUCCESS' });
  const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(f.props.onSettled).toHaveBeenCalledWith(CHILD, 'SUCCESS'));
  expect(answerHumanQuestion).not.toHaveBeenCalled(); await waitFor(() => expect(result.current.phase).toBe('settled'));
});

test('cancel does not claim success if answer already won the server transaction', async () => {
  const f = fixture(); cancelHumanQuestion.mockResolvedValue(f.accepted);
  const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(result.current.phase).toBe('pending'));
  await act(async () => { await result.current.cancel(); });
  expect(f.props.onAccepted).toHaveBeenCalledWith(f.accepted);
  expect(result.current.notice).not.toContain('отменён');
});

test('late answers cannot start a child in another thread or account', async () => {
  const f = fixture(); let release;
  answerHumanQuestion.mockReturnValue(new Promise(resolve => { release = resolve; }));
  const { result, rerender } = renderHook(props => useHumanQuestion(props), { initialProps: f.props });
  await waitFor(() => expect(result.current.phase).toBe('pending'));
  act(() => result.current.setText('PRIVATE-DRAFT'));
  let operation; act(() => { operation = result.current.submit(); });
  rerender({ ...f.props, threadId: 'other-thread', accountId: 'other-account', messages: [] });
  await act(async () => { release(f.accepted); await operation; });
  expect(f.props.onAccepted).not.toHaveBeenCalled(); expect(result.current.blocking).toBe(false);
  expect(result.current.draft.text).toBe('');
});

test('a changed project cannot submit, and an expired server question restores the normal input', async () => {
  const f = fixture(); f.props.context.blocked = true;
  const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(result.current.phase).toBe('pending'));
  act(() => result.current.setText('Продолжить'));
  await act(async () => { await result.current.submit(); });
  expect(answerHumanQuestion).not.toHaveBeenCalled();
  readHumanQuestion.mockResolvedValue({ ...f.question, state: 'expired' });
  await act(async () => { await result.current.refresh(); });
  expect(result.current.blocking).toBe(false); expect(result.current.notice).toContain('истёк');
});

test('an unverified accepted snapshot cannot read a cost or start the child in another owner', async () => {
  const f = fixture(); f.props.messages = [{ type: 'agent', metadata: { human_question: f.accepted } }];
  readHumanQuestion.mockRejectedValue(new Error('not-owned'));
  const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(result.current.phase).toBe('unavailable'));
  expect(readHumanQuestionCost).not.toHaveBeenCalled(); expect(f.props.onAccepted).not.toHaveBeenCalled();
  expect(result.current.verified).toBe(false);
});

test('an accepted answer waits for the same-child cost decision before trace, Stop and task polling', async () => {
  const f = fixture();
  const quote = { offer_id: '88888888-8888-4888-8888-888888888888', state: 'pending', estimated_credits: 5000, expires_at: f.question.expires_at };
  readHumanQuestionCost.mockResolvedValue(quote);
  decideHumanQuestionCost.mockRejectedValueOnce(new Error('lost-ack'));
  const { result } = renderHook(() => useHumanQuestion(f.props));
  await waitFor(() => expect(result.current.phase).toBe('pending'));
  act(() => result.current.setText('Продолжить'));
  await act(async () => { await result.current.submit(); });
  await waitFor(() => expect(result.current.phase).toBe('cost_pending'));
  expect(result.current.costMode).toBe(true); expect(result.current.blocking).toBe(true);
  expect(f.props.onAccepted).not.toHaveBeenCalled(); expect(getTaskStatus).not.toHaveBeenCalled();
  await act(async () => { await result.current.cost.decide('accept'); });
  expect(result.current.phase).toBe('cost_unknown'); expect(f.props.onAccepted).not.toHaveBeenCalled();
  readHumanQuestionCost.mockResolvedValue({ ...quote, state: 'accepted' });
  await act(async () => { await result.current.cost.refresh(); });
  await waitFor(() => expect(f.props.onAccepted).toHaveBeenCalledTimes(1));
  expect(result.current.blocking).toBe(false); expect(result.current.costMode).toBe(false);
  expect(getTaskStatus).toHaveBeenCalledWith(CHILD, expect.any(Object));
  expect(answerHumanQuestion).toHaveBeenCalledTimes(1); expect(decideHumanQuestionCost).toHaveBeenCalledTimes(1);
});
