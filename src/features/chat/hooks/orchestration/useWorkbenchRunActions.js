import { useCallback } from 'react';
import { latestTimelineMessage } from '../../utils/latestTimelineMessage';

/** Reuse Chat's job, cancellation and trace owners for workbench continuations. */
export function useWorkbenchRunActions({ messages, currentJob, wsCallbacks, startTraceSession,
  appendTraceEvent, finalizeTraceSession, clearCurrentJob, setIsLoading, reloadHistory, cancelJob, notify }) {
  const handleQuestionAccepted = useCallback(question => {
    if (currentJob?.id && ![question.source_job_id, question.resume_job_id].includes(currentJob.id)) return;
    const anchor = latestTimelineMessage(messages, message => message.type === 'user'
      && (question.surface === 'ide' ? message.metadata?.ide_repository : message.metadata?.document_project) === question.project_id);
    startTraceSession(anchor?.content || 'Продолжение запроса', anchor?.id);
    appendTraceEvent({ kind: 'info', title: 'Ответ принят', detail: 'Продолжение сохранено. Ожидаю выполнения.' });
    wsCallbacks.onJobCreated({ job_id: question.resume_job_id, celery_task_id: question.resume_job_id,
      ...(question.surface === 'pdf' ? { document_project: question.project_id } : {}) });
  }, [appendTraceEvent, currentJob?.id, messages, startTraceSession, wsCallbacks]);
  const handleQuestionSettled = useCallback((childId, status) => {
    if (currentJob?.id && currentJob.id !== childId) return;
    clearCurrentJob(); setIsLoading(false);
    finalizeTraceSession(status === 'SUCCESS' ? 'done' : 'error');
    reloadHistory();
  }, [clearCurrentJob, currentJob?.id, finalizeTraceSession, reloadHistory, setIsLoading]);
  const handleCancelJob = useCallback(async celeryTaskId => {
    // Preserve the existing immediate UI Stop; network acknowledgement is separate.
    setIsLoading(false);
    clearCurrentJob();
    appendTraceEvent({ kind: 'error', title: 'Остановлено пользователем', detail: 'Работа прервана кнопкой «стоп»' });
    finalizeTraceSession('error');
    try { await cancelJob(celeryTaskId); }
    catch {
      notify({ title: 'Ошибка отмены', description: 'Не удалось отменить задачу. Попробуйте ещё раз.', status: 'warning', duration: 3000 });
    }
  }, [appendTraceEvent, cancelJob, clearCurrentJob, finalizeTraceSession, notify, setIsLoading]);
  return { handleQuestionAccepted, handleQuestionSettled, handleCancelJob };
}
