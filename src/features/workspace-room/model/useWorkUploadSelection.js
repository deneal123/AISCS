import { useCallback, useEffect, useRef, useState } from 'react';
import { createIntentId as uploadIntentId } from '@shared/utils/createIntentId';

export { uploadIntentId };

const EMPTY = { selected: null, state: 'idle', progress: 0 };

// The thread workbench owns the selected File and retry intent, not whichever
// upload control is currently rendered in its source panel.
export function useWorkUploadSelection({ scope, disabled, busy, onUpload, onPartial, uploadOptions }) {
  const [selection, setSelection] = useState(EMPTY);
  const controllerRef = useRef(null);
  const timerRef = useRef(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    generationRef.current += 1;
    setSelection(EMPTY);
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = null;
      // The request model owns abort/reconciliation on thread change/unmount.
      // Replacing a presentation control must not cancel a committed upload.
      controllerRef.current = null;
    };
  }, [scope]);

  const start = useCallback(async (candidate, intentId = uploadIntentId(), options = uploadOptions) => {
    if (!candidate || disabled || busy || controllerRef.current) return;
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    const generation = generationRef.current;
    const controller = new AbortController();
    controllerRef.current = controller;
    const isCurrent = () => mountedRef.current && generation === generationRef.current;
    const pinnedOptions = { ...options };
    setSelection({ selected: { file: candidate, intentId, options: pinnedOptions }, state: 'uploading', progress: 0 });
    let result;
    try {
      result = await onUpload?.(candidate, {
        ...pinnedOptions,
        signal: controller.signal,
        uploadIntentId: intentId,
        onProgress: (value) => {
          if (isCurrent() && !controller.signal.aborted) {
            setSelection((old) => ({ ...old, progress: Number.isFinite(value) ? value : 0 }));
          }
        },
      });
    } catch {
      result = { ok: false };
    }
    if (!isCurrent()) return;
    if (controllerRef.current === controller) controllerRef.current = null;
    let state;
    if (controller.signal.aborted || result?.cancelled) state = 'cancelled';
    else if (result === true || result?.ok) {
      state = result?.outcome === 'library_saved' ? 'partial'
        : result?.outcome === 'kept' ? 'kept' : 'complete';
    } else state = result?.status === 409 ? 'conflict' : 'error';
    setSelection((old) => ({ ...old, state, progress: ['kept', 'complete'].includes(state) ? 100 : old.progress }));
    if (state === 'partial') onPartial?.(result);
    if (['kept', 'complete'].includes(state)) {
      timerRef.current = window.setTimeout(() => {
        if (isCurrent()) setSelection(EMPTY);
        timerRef.current = null;
      }, 1200);
    }
  }, [busy, disabled, onPartial, onUpload, uploadOptions]);

  const cancel = useCallback(() => controllerRef.current?.abort(), []);
  return { ...selection, start, cancel };
}
