import { useCallback, useEffect, useState } from 'react';
import { useWorkspaceNavigationGuard } from './useWorkspaceNavigationGuard';

/**
 * Own the URL-backed Chat/Work peer-surface lifecycle.
 *
 * Merely selecting Work updates the URL and mounts its read-only snapshot. It
 * never activates a sandbox. Leaving a dirty editor is the only transition
 * that requires confirmation.
 */
export function useChatWorkSurface({ location, navigate }) {
  const activeSurface = new URLSearchParams(location.search).get('surface') === 'work'
    ? 'work'
    : 'chat';
  const [workMounted, setWorkMounted] = useState(activeSurface === 'work');
  const [pendingSurface, setPendingSurface] = useState('');
  const guard = useWorkspaceNavigationGuard();

  const applySurface = useCallback((nextSurface) => {
    const params = new URLSearchParams(location.search);
    if (nextSurface === 'work') params.set('surface', 'work');
    else params.delete('surface');
    const search = params.toString();
    navigate(`${location.pathname}${search ? `?${search}` : ''}`);
  }, [location.pathname, location.search, navigate]);

  const changeSurface = useCallback((nextSurface) => {
    if (nextSurface === activeSurface) return;
    setPendingSurface(nextSurface);
    const executed = guard.requestAction(() => applySurface(nextSurface));
    if (executed) setPendingSurface('');
  }, [activeSurface, applySurface, guard]);

  const openWorkSurface = useCallback(() => changeSurface('work'), [changeSurface]);
  const cancelSurfaceChange = useCallback(() => {
    setPendingSurface('');
    guard.cancel();
  }, [guard]);

  const confirmSurfaceChange = useCallback(async () => {
    setPendingSurface('');
    await guard.confirm();
  }, [guard]);

  useEffect(() => {
    if (activeSurface === 'work') setWorkMounted(true);
  }, [activeSurface]);

  return {
    activeSurface,
    workMounted,
    pendingSurface,
    navigationPending: guard.pending,
    cancelSurfaceRef: guard.cancelRef,
    changeSurface,
    openWorkSurface,
    setWorkspaceDirty: guard.setDirty,
    requestGuardedAction: guard.requestAction,
    registerWorkspaceLifecycle: guard.registerLifecycle,
    cancelSurfaceChange,
    confirmSurfaceChange,
  };
}

export default useChatWorkSurface;
