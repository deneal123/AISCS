import { useCallback, useEffect, useState } from 'react';
import { useWorkspaceNavigationGuard } from './useWorkspaceNavigationGuard';
import { useWorkbenchLibraryNavigation } from './useWorkbenchLibraryNavigation';

/**
 * Own the URL-backed Chat/Work peer-surface lifecycle.
 *
 * Merely selecting Work updates the URL and mounts its read-only snapshot. It
 * never activates a sandbox. Leaving a dirty editor is the only transition
 * that requires confirmation.
 */
export function useChatWorkSurface({ location, navigate, sidebar, profileDisclosure }) {
  const requested = new URLSearchParams(location.search).get('surface');
  const activeSurface = ['work', 'pdf'].includes(requested) ? requested : 'chat';
  const [workMounted, setWorkMounted] = useState(activeSurface !== 'chat');
  const ensureWorkMounted = useCallback(() => setWorkMounted(true), []);
  const library = useWorkbenchLibraryNavigation({ pathname: location.pathname, ensureWorkMounted, sidebar });
  const [pendingSurface, setPendingSurface] = useState('');
  const guard = useWorkspaceNavigationGuard(location.pathname);

  // Account-menu profile navigation belongs to the same URL owner as peers.
  // Consume only its query flag, preserving the thread, surface and other state.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('profile') !== 'open' || !profileDisclosure) return;
    profileDisclosure.onOpen();
    params.delete('profile');
    const search = params.toString();
    navigate(`${location.pathname}${search ? `?${search}` : ''}`, { replace: true });
  }, [location.search, location.pathname, navigate, profileDisclosure]);

  const applySurface = useCallback((nextSurface) => {
    const params = new URLSearchParams(location.search);
    if (['work', 'pdf'].includes(nextSurface)) params.set('surface', nextSurface);
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
  const openPdfSurface = useCallback(() => changeSurface('pdf'), [changeSurface]);
  const cancelSurfaceChange = useCallback(() => {
    if (guard.cancel() !== false) setPendingSurface('');
  }, [guard]);

  const confirmSurfaceChange = useCallback(async () => {
    if (await guard.confirm() !== false) setPendingSurface('');
  }, [guard]);

  useEffect(() => {
    if (activeSurface !== 'chat') setWorkMounted(true);
  }, [activeSurface]);

  return {
    activeSurface,
    workMounted,
    ensureWorkMounted,
    library,
    pendingSurface,
    navigationPending: guard.pending,
    cancelSurfaceRef: guard.cancelRef,
    navigationFinalFocusRef: guard.finalFocusRef,
    changeSurface,
    openWorkSurface,
    openPdfSurface,
    setWorkspaceDirty: guard.setDirty,
    requestGuardedAction: guard.requestAction,
    registerWorkspaceLifecycle: guard.registerLifecycle,
    cancelSurfaceChange,
    confirmSurfaceChange,
  };
}

export default useChatWorkSurface;
