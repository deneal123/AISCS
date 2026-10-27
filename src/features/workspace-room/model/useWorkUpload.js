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
  const activeRef = useRef(false);
  const threadRef = useRef(threadId);
  threadRef.current = threadId;

  useEffect(() => {
    activeRef.current = true;
    generationRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setBusy(false);
    setLastResult(null);
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [threadId]);

  const upload = useCallback(async (selectedFile, {
    signal,
    onProgress,
    uploadIntentId,
    libraryOnly = false,
  } = {}) => {
    // A retained callback may belong to another thread or an unmounted owner.
    // Reject before it can supersede the currently owned request.
    if (!activeRef.current || threadRef.current !== threadId) {
      return { ok: false, cancelled: true, status: 0 };
    }
    if (!threadId || !selectedFile || !uploadIntentId) return { ok: false, status: 422 };
    if (signal?.aborted) return { ok: false, cancelled: true, status: 0 };
    const expectedThread = threadId;
    const generation = ++generationRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const isCurrent = () => activeRef.current && generation === generationRef.current
      && threadRef.current === expectedThread;
    const reconcile = async () => {
      try {
        await refreshSnapshot?.({ background: true });
      } catch {
        // Snapshot availability is independent of the confirmed upload outcome.
        // The snapshot owner retains its own bounded recovery state.
      }
    };
    const forwardAbort = () => controller.abort();
    signal?.addEventListener('abort', forwardAbort, { once: true });
    setBusy(true);
    setLastResult(null);
    try {
      const { uploadFileToWorkspace, uploadFileToLibrary } = await import('@api/chat');
      if (!isCurrent() || controller.signal.aborted) {
        return { ok: false, cancelled: true, status: 0 };
      }
      // Fence zero deliberately delegates activate -> capability -> lease ->
      // revision preflight to one backend operation.  A passive Work GET still
      // never provisions a sandbox.
      const progress = (value) => {
        if (isCurrent() && !controller.signal.aborted) onProgress?.(value);
      };
      const requestOptions = { signal: controller.signal, uploadIntentId, actorSession };
      const result = libraryOnly ? await uploadFileToLibrary(threadId, selectedFile, progress, requestOptions) : await uploadFileToWorkspace(
        threadId,
        selectedFile,
        '',
        0,
        progress,
        requestOptions,
      );
      if (!isCurrent()) {
        return { ok: false, cancelled: true, status: 0 };
      }
      if (controller.signal.aborted) throw new DOMException('Upload cancelled', 'AbortError');
      const outcome = String(result?.outcome || 'library_saved');
      if (libraryOnly && (outcome !== 'library_uploaded' || !result?.file?.file_id)) throw new Error('library_upload_unconfirmed');
      const next = { ok: true, ...result, outcome };
      setLastResult(next);
      if (outcome === 'library_uploaded') {
        notify?.({ title: 'Файл сохранён в библиотеке', description: 'Добавление в проект — отдельное действие.', status: 'success', duration: 2800 });
      } else if (outcome === 'imported') {
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
      await reconcile();
      return isCurrent() ? next : { ok: false, cancelled: true, status: 0 };
    } catch (error) {
      const status = statusOf(error) || 503;
      if (!isCurrent()) {
        return { ok: false, cancelled: true, status: 0 };
      }
      // Cancellation and transport ambiguity may happen after the backend
      // committed UserFile. Reconcile first; a retry reuses the same intent.
      await reconcile();
      if (!isCurrent()) return { ok: false, cancelled: true, status: 0 };
      const wasCancelled = cancelled(error) || controller.signal.aborted;
      if (!wasCancelled) {
        notify?.({
          title: status === 409 ? 'Этот повтор относится к другому файлу' : 'Статус загрузки не подтверждён',
          description: status === 409
            ? 'Выберите файл заново.'
            : 'Проверьте библиотеку перед безопасным повтором.',
          status: 'warning',
          duration: 4000,
        });
      }
      const next = { ok: false, cancelled: wasCancelled, status };
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
