import { useCallback, useEffect, useRef, useState } from 'react';
import { useBlocker } from 'react-router-dom';

const surfaceOf = (location) => new URLSearchParams(location.search).get('surface');

/**
 * Owns the single unsaved-work transition contract for the Chat route. Router
 * transitions and local Work actions share one pending action and one dialog.
 */
export function useWorkspaceNavigationGuard(scope = '') {
  const [dirty, setDirty] = useState(false);
  const [manualPending, setManualPending] = useState(false);
  const cancelRef = useRef(null);
  const lifecycleRef = useRef(new Map());
  const dirtyOwnersRef = useRef(new Map());
  const manualActionRef = useRef(null);
  const finalFocusRef = useRef(null);
  const confirmingRef = useRef(null);
  const bypassBlockerRef = useRef(false);
  const mountedRef = useRef(true);
  const scopeRef = useRef({ scope });
  if (scopeRef.current.scope !== scope) scopeRef.current = { scope };
  const owner = scopeRef.current;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const canAct = useCallback(() => mountedRef.current && scopeRef.current === owner, [owner]);
  const setScopedDirty = useCallback((value, source = 'workspace') => {
    if (!canAct()) return;
    dirtyOwnersRef.current.set(source, Boolean(value));
    const next = [...dirtyOwnersRef.current.values()].some(Boolean);
    dirtyRef.current = next;
    setDirty(next);
  }, [canAct]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      confirmingRef.current = null;
      manualActionRef.current = null;
    };
  }, []);

  useEffect(() => {
    confirmingRef.current = null;
    manualActionRef.current = null;
    finalFocusRef.current = null;
    bypassBlockerRef.current = false;
    setManualPending(false);
    dirtyOwnersRef.current.clear();
    setDirty(false);
  }, [owner]);

  const blocker = useBlocker(useCallback(({ currentLocation, nextLocation }) => (
    dirty
    && !bypassBlockerRef.current
    && (
      currentLocation.pathname !== nextLocation.pathname
      || surfaceOf(currentLocation) !== surfaceOf(nextLocation)
    )
  ), [dirty]));
  const blockerRef = useRef(blocker);
  blockerRef.current = blocker;

  const registerLifecycle = useCallback((lifecycle, source = 'workspace') => {
    if (!canAct()) return undefined;
    const registered = {
      abandon: typeof lifecycle?.abandon === 'function' ? lifecycle.abandon : null,
      editorRef: lifecycle?.editorRef || null,
    };
    lifecycleRef.current.set(source, registered);
    return () => {
      if (lifecycleRef.current.get(source) === registered) lifecycleRef.current.delete(source);
    };
  }, [canAct]);

  const requestAction = useCallback((action, options = {}) => {
    if (!canAct() || confirmingRef.current || typeof action !== 'function') return false;
    if (!dirtyRef.current) {
      action();
      return true;
    }
    if (manualActionRef.current || blockerRef.current.state === 'blocked') return false;
    finalFocusRef.current = null;
    manualActionRef.current = {
      action,
      returnFocus: options.returnFocus
        || (typeof document === 'undefined' ? null : document.activeElement),
    };
    setManualPending(true);
    return false;
  }, [canAct]);

  const cancel = useCallback(() => {
    if (!canAct()) return false;
    confirmingRef.current = null;
    const pending = manualActionRef.current;
    manualActionRef.current = null;
    setManualPending(false);
    if (blockerRef.current.state === 'blocked') blockerRef.current.reset();
    const editor = [...lifecycleRef.current.entries()].find(([source]) => dirtyOwnersRef.current.get(source))?.[1].editorRef?.current;
    finalFocusRef.current = editor?.isConnected ? editor
      : pending?.returnFocus?.isConnected ? pending.returnFocus : null;
    return true;
  }, [canAct]);

  const confirm = useCallback(async () => {
    if (!canAct() || confirmingRef.current) return false;
    const operation = {};
    confirmingRef.current = operation;
    finalFocusRef.current = null;
    const pending = manualActionRef.current;
    manualActionRef.current = null;
    setManualPending(false);
    try {
      const owners = [...lifecycleRef.current.entries()].filter(([source]) => dirtyOwnersRef.current.get(source));
      let discarded = true;
      for (const [, lifecycle] of owners.length ? owners : lifecycleRef.current.entries()) {
        if (await lifecycle.abandon?.() === false) { discarded = false; break; }
      }
      if (!canAct() || confirmingRef.current !== operation) return false;
      if (discarded === false) {
        manualActionRef.current = pending;
        setManualPending(Boolean(pending));
        return false;
      }
      bypassBlockerRef.current = true;
      dirtyOwnersRef.current.clear();
      dirtyRef.current = false;
      setDirty(false);
      if (blockerRef.current.state === 'blocked') blockerRef.current.proceed();
      else await pending?.action?.();
      return true;
    } finally {
      if (confirmingRef.current === operation) confirmingRef.current = null;
    }
  }, [canAct]);

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
    setDirty: setScopedDirty,
    pending: manualPending || blocker.state === 'blocked',
    cancelRef,
    finalFocusRef,
    requestAction,
    registerLifecycle,
    cancel,
    confirm,
  };
}

export default useWorkspaceNavigationGuard;
