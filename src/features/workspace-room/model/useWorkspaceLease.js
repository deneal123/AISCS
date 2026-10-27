import { useCallback, useEffect, useRef, useState } from 'react';
import { getWorkspaceActorSession } from './workspaceSession';

const EMPTY_LEASE = { threadId: '', path: '', fence: 0, status: 'idle', reason: '' };
const statusOf = (error) => Number(error?.status || error?.response?.status || 0);

export function useWorkspaceLease({ threadId, active = true, notify }) {
  const [lease, setLease] = useState(EMPTY_LEASE);
  const leaseRef = useRef(EMPTY_LEASE);
  const generationRef = useRef(0);
  const actorSessionRef = useRef(getWorkspaceActorSession());
  const currentThreadRef = useRef(threadId);
  const activeRef = useRef(active);
  const mountedRef = useRef(true);
  currentThreadRef.current = threadId;
  activeRef.current = active;

  const remember = useCallback((next) => {
    leaseRef.current = next;
    setLease(next);
    return next;
  }, []);

  const releaseTarget = useCallback(async (target) => {
    if (!target?.threadId || !target?.path || !target?.fence) return;
    try {
      const { releaseWorkspaceLease } = await import('@api/chat');
      await releaseWorkspaceLease(target.threadId, target.path, target.fence, {
        actorSession: actorSessionRef.current,
      });
    } catch {
      // The lease has a short server-side TTL.  A failed release cannot be
      // allowed to erase the local draft or masquerade as a successful write.
    }
  }, []);

  const release = useCallback(async ({ reason = 'released' } = {}) => {
    const target = leaseRef.current;
    generationRef.current += 1;
    remember({
      threadId: target.threadId,
      path: target.path,
      fence: 0,
      status: target.path ? reason : 'idle',
      reason,
    });
    await releaseTarget(target);
  }, [releaseTarget, remember]);

  const acquire = useCallback(async (path) => {
    const normalizedPath = String(path || '');
    const stale = () => ({
      threadId, path: normalizedPath, fence: 0, status: 'stale', reason: 'thread_changed',
    });
    if (!mountedRef.current || currentThreadRef.current !== threadId || activeRef.current !== active) return stale();
    if (!threadId || !normalizedPath || !active) {
      return remember({
        threadId: threadId || '', path: normalizedPath, fence: 0, status: 'readonly', reason: 'inactive',
      });
    }
    const previous = leaseRef.current;
    const generation = ++generationRef.current;
    const isCurrent = () => mountedRef.current && activeRef.current
      && generation === generationRef.current && currentThreadRef.current === threadId;
    if (previous.fence && (previous.threadId !== threadId || previous.path !== normalizedPath)) {
      await releaseTarget(previous);
    }
    if (!isCurrent()) return stale();
    remember({
      threadId, path: normalizedPath, fence: 0, status: 'acquiring', reason: '',
    });
    try {
      const { acquireWorkspaceLease } = await import('@api/chat');
      if (!isCurrent()) return stale();
      const result = await acquireWorkspaceLease(threadId, normalizedPath, {
        actorSession: actorSessionRef.current,
      });
      if (!isCurrent()) {
        await releaseTarget({ threadId, path: normalizedPath, fence: Number(result?.fence || 0) });
        return stale();
      }
      return remember({
        threadId,
        path: normalizedPath,
        fence: Number(result?.fence || 0),
        status: Number(result?.fence || 0) ? 'editing' : 'readonly',
        reason: Number(result?.fence || 0) ? '' : 'unavailable',
      });
    } catch (error) {
      if (!isCurrent()) return stale();
      const status = statusOf(error);
      return remember({
        threadId,
        path: normalizedPath,
        fence: 0,
        status: 'readonly',
        reason: status === 409 || status === 423 ? 'occupied' : 'unavailable',
      });
    }
  }, [active, releaseTarget, remember, threadId]);

  const reacquire = useCallback(() => acquire(leaseRef.current.path), [acquire]);

  useEffect(() => {
    const current = leaseRef.current;
    if (!current.threadId || current.threadId === threadId) return;
    generationRef.current += 1;
    releaseTarget(current);
    remember(EMPTY_LEASE);
  }, [releaseTarget, remember, threadId]);

  useEffect(() => {
    if (active || !leaseRef.current.path) return;
    release({ reason: 'inactive' });
  }, [active, release]);

  useEffect(() => {
    if (!active || !lease.threadId || !lease.path || !lease.fence) return undefined;
    let pending = false;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (pending || cancelled) return;
      const target = leaseRef.current;
      const generation = generationRef.current;
      const isCurrent = () => !cancelled && mountedRef.current && activeRef.current
        && generation === generationRef.current
        && currentThreadRef.current === target.threadId
        && leaseRef.current.threadId === target.threadId
        && leaseRef.current.path === target.path && leaseRef.current.fence === target.fence;
      if (!target.fence || !isCurrent()) return;
      pending = true;
      try {
        const { renewWorkspaceLease } = await import('@api/chat');
        if (!isCurrent()) return;
        const result = await renewWorkspaceLease(target.threadId, target.path, target.fence, {
          actorSession: actorSessionRef.current,
        });
        if (!isCurrent()) return;
        remember({ ...target, fence: Number(result?.fence || target.fence), status: 'editing' });
      } catch {
        if (!isCurrent()) return;
        remember({ ...target, fence: 0, status: 'lost', reason: 'expired' });
        notify?.({
          title: 'Право на правку истекло',
          description: 'Текст сохранён в редакторе. Получите право на правку повторно.',
          status: 'warning',
          duration: 4500,
        });
      } finally {
        pending = false;
      }
    }, 20_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [active, lease.fence, lease.path, lease.threadId, notify, remember]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      releaseTarget(leaseRef.current);
    };
  }, [releaseTarget]);

  return {
    lease,
    actorSession: actorSessionRef.current,
    acquire,
    reacquire,
    release,
    releaseTarget,
  };
}
