import { useCallback, useEffect, useRef, useState } from 'react';
import { getWorkspaceActorSession } from './workspaceSession';

const statusOf = (error) => Number(error?.status || error?.response?.status || 0);
const cancelled = (error) => error?.name === 'CanceledError'
  || error?.name === 'AbortError'
  || error?.code === 'ERR_CANCELED';

export function useWorkUpload({ threadId, refreshSnapshot, notify }) {
  const actorSession = getWorkspaceActorSession();
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const controllerRef = useRef(null);
  const generationRef = useRef(0);
  const threadRef = useRef(threadId);
  threadRef.current = threadId;

  useEffect(() => {
    generationRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setBusy(false);
    setLastResult(null);
    return () => {
      generationRef.current += 1;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [threadId]);

  const upload = useCallback(async (selectedFile, {
    signal,
    onProgress,
    uploadIntentId,
  } = {}) => {
    if (!threadId || !selectedFile || !uploadIntentId) return { ok: false, status: 422 };
    const expectedThread = threadId;
    const generation = ++generationRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const forwardAbort = () => controller.abort();
    signal?.addEventListener('abort', forwardAbort, { once: true });
    setBusy(true);
    setLastResult(null);
    try {
      const { uploadFileToWorkspace } = await import('@api/chat');
      // Fence zero deliberately delegates activate -> capability -> lease ->
      // revision preflight to one backend operation.  A passive Work GET still
      // never provisions a sandbox.
      const result = await uploadFileToWorkspace(
        threadId,
        selectedFile,
        '',
        0,
        onProgress,
        { signal: controller.signal, uploadIntentId, actorSession },
      );
      if (generation !== generationRef.current || threadRef.current !== expectedThread) {
        return { ok: false, cancelled: true, status: 0 };
      }
      const outcome = String(result?.outcome || 'library_saved');
      const next = { ok: true, ...result, outcome };
      setLastResult(next);
      if (outcome === 'imported') {
        notify?.({
          title: 'Файл добавлен в библиотеку и рабочее место',
          status: 'success',
          duration: 2800,
        });
      } else if (outcome === 'kept') {
        notify?.({
          title: 'Источник сохранён; файл с таким именем уже есть в рабочем месте',
          status: 'info',
          duration: 3800,
        });
      } else {
        notify?.({
          title: 'Файл сохранён в библиотеке',
          description: 'Рабочая копия пока не создана. Исходник не потерян.',
          status: 'warning',
          duration: 4500,
        });
      }
      await refreshSnapshot?.({ background: true });
      return next;
    } catch (error) {
      const status = statusOf(error) || 503;
      if (generation !== generationRef.current || threadRef.current !== expectedThread) {
        return { ok: false, cancelled: true, status: 0 };
      }
      // Cancellation and transport ambiguity may happen after the backend
      // committed UserFile. Reconcile first; a retry reuses the same intent.
      await refreshSnapshot?.({ background: true });
      if (!cancelled(error)) {
        notify?.({
          title: status === 409 ? 'Этот повтор относится к другому файлу' : 'Статус загрузки уточнён',
          description: status === 409
            ? 'Выберите файл заново.'
            : 'Проверьте библиотеку перед безопасным повтором.',
          status: 'warning',
          duration: 4000,
        });
      }
      const next = { ok: false, cancelled: cancelled(error), status };
      setLastResult(next);
      return next;
    } finally {
      signal?.removeEventListener('abort', forwardAbort);
      if (controllerRef.current === controller) controllerRef.current = null;
      if (generation === generationRef.current && threadRef.current === expectedThread) {
        setBusy(false);
      }
    }
  }, [actorSession, notify, refreshSnapshot, threadId]);

  return { upload, busy, lastResult, clearResult: () => setLastResult(null) };
}
