import { useCallback, useEffect, useRef, useState } from 'react';
import { useBlocker } from 'react-router-dom';

const surfaceOf = (location) => new URLSearchParams(location.search).get('surface');

/**
 * Owns the single unsaved-work transition contract for the Chat route. Router
 * transitions and local Work actions share one pending action and one dialog.
 */
export function useWorkspaceNavigationGuard() {
  const [dirty, setDirty] = useState(false);
  const [manualPending, setManualPending] = useState(false);
  const cancelRef = useRef(null);
  const lifecycleRef = useRef({ abandon: null, focusEditor: null });
  const manualActionRef = useRef(null);
  const confirmingRef = useRef(false);
  const bypassBlockerRef = useRef(false);

  const blocker = useBlocker(useCallback(({ currentLocation, nextLocation }) => (
    dirty
    && !bypassBlockerRef.current
    && (
      currentLocation.pathname !== nextLocation.pathname
      || surfaceOf(currentLocation) !== surfaceOf(nextLocation)
    )
  ), [dirty]));

  const registerLifecycle = useCallback((lifecycle) => {
    lifecycleRef.current = {
      abandon: typeof lifecycle?.abandon === 'function' ? lifecycle.abandon : null,
      focusEditor: typeof lifecycle?.focusEditor === 'function' ? lifecycle.focusEditor : null,
    };
    return () => {
      if (lifecycleRef.current.abandon === lifecycle?.abandon) {
        lifecycleRef.current = { abandon: null, focusEditor: null };
      }
    };
  }, []);

  const requestAction = useCallback((action, options = {}) => {
    if (typeof action !== 'function') return false;
    if (!dirty) {
      action();
      return true;
    }
    if (manualActionRef.current || blocker.state === 'blocked') return false;
    manualActionRef.current = {
      action,
      returnFocus: options.returnFocus
        || (typeof document === 'undefined' ? null : document.activeElement),
    };
    setManualPending(true);
    return false;
  }, [blocker.state, dirty]);

  const cancel = useCallback(() => {
    const pending = manualActionRef.current;
    manualActionRef.current = null;
    setManualPending(false);
    if (blocker.state === 'blocked') blocker.reset();
    queueMicrotask(() => {
      if (pending?.returnFocus?.focus) pending.returnFocus.focus();
      else lifecycleRef.current.focusEditor?.();
    });
  }, [blocker]);

  const confirm = useCallback(async () => {
    if (confirmingRef.current) return;
    confirmingRef.current = true;
    const pending = manualActionRef.current;
    manualActionRef.current = null;
    setManualPending(false);
    try {
      await lifecycleRef.current.abandon?.();
      bypassBlockerRef.current = true;
      setDirty(false);
      if (blocker.state === 'blocked') blocker.proceed();
      else await pending?.action?.();
    } finally {
      confirmingRef.current = false;
    }
  }, [blocker]);

  useEffect(() => {
    if (blocker.state !== 'blocked' || manualActionRef.current) return;
    manualActionRef.current = {
      action: null,
      returnFocus: typeof document === 'undefined' ? null : document.activeElement,
    };
  }, [blocker.state]);

  useEffect(() => {
    if (!dirty) return undefined;
    const handleBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (!dirty) bypassBlockerRef.current = false;
  }, [dirty]);

  return {
    dirty,
    setDirty,
    pending: manualPending || blocker.state === 'blocked',
    cancelRef,
    requestAction,
    registerLifecycle,
    cancel,
    confirm,
  };
}

export default useWorkspaceNavigationGuard;
