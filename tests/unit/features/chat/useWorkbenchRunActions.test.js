import { act, renderHook } from '@testing-library/react';
import { useWorkbenchRunActions } from '@features/chat/hooks/orchestration/useWorkbenchRunActions';

function fixture() {
  return { messages: [], currentJob: null, wsCallbacks: { onJobCreated: jest.fn() },
    startTraceSession: jest.fn(), appendTraceEvent: jest.fn(), finalizeTraceSession: jest.fn(),
    clearCurrentJob: jest.fn(), setIsLoading: jest.fn(), reloadHistory: jest.fn(),
    cancelJob: jest.fn().mockResolvedValue({}), notify: jest.fn() };
}
const question = { surface: 'pdf', project_id: 'project', source_job_id: 'source', resume_job_id: 'child' };

test('accepted continuation reuses the original latest project anchor and same cancellable child', () => {
  const props = fixture();
  const user = { id: 'original', type: 'user', content: 'Первый слайд', timestamp: '2026-10-19T10:00:00Z', metadata: { document_project: 'project' } };
  props.messages = [user, { ...user, id: 'old', timestamp: '2026-10-18T10:00:00Z' }, { ...user, id: 'foreign', metadata: { document_project: 'other' } }];
  const { result } = renderHook(() => useWorkbenchRunActions(props));
  act(() => result.current.handleQuestionAccepted(question));
  expect(props.startTraceSession).toHaveBeenCalledWith('Первый слайд', 'original');
  expect(props.wsCallbacks.onJobCreated).toHaveBeenCalledWith({ job_id: 'child', celery_task_id: 'child', document_project: 'project' });
  act(() => result.current.handleQuestionSettled('child', 'SUCCESS'));
  expect(props.finalizeTraceSession).toHaveBeenCalledWith('done');
  expect(props.reloadHistory).toHaveBeenCalledTimes(1);
});

test('a different active job cannot be replaced or cleared by question recovery', () => {
  const props = { ...fixture(), currentJob: { id: 'other' } };
  const { result } = renderHook(() => useWorkbenchRunActions(props));
  act(() => { result.current.handleQuestionAccepted(question); result.current.handleQuestionSettled('child', 'SUCCESS'); });
  expect(props.wsCallbacks.onJobCreated).not.toHaveBeenCalled();
  expect(props.clearCurrentJob).not.toHaveBeenCalled();
});

test('Stop retains immediate UI feedback and reports a failed native cancellation without replay', async () => {
  const props = fixture();
  let reject;
  props.cancelJob.mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  const { result } = renderHook(() => useWorkbenchRunActions(props));
  let pending;
  act(() => { pending = result.current.handleCancelJob('child'); });
  expect(props.setIsLoading).toHaveBeenCalledWith(false);
  expect(props.finalizeTraceSession).toHaveBeenCalledWith('error');
  await act(async () => { reject(new Error('PRIVATE')); await pending; });
  expect(props.cancelJob).toHaveBeenCalledTimes(1);
  expect(props.notify).toHaveBeenCalledWith(expect.objectContaining({ title: 'Ошибка отмены', status: 'warning' }));
});
