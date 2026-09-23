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
  currentThreadRef.current = threadId;

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
    if (!threadId || !normalizedPath || !active) {
      return remember({
        threadId: threadId || '', path: normalizedPath, fence: 0, status: 'readonly', reason: 'inactive',
      });
    }
    const previous = leaseRef.current;
    const generation = ++generationRef.current;
    if (previous.fence && (previous.threadId !== threadId || previous.path !== normalizedPath)) {
      await releaseTarget(previous);
    }
    remember({
      threadId, path: normalizedPath, fence: 0, status: 'acquiring', reason: '',
    });
    try {
      const { acquireWorkspaceLease } = await import('@api/chat');
      const result = await acquireWorkspaceLease(threadId, normalizedPath, {
        actorSession: actorSessionRef.current,
      });
      if (generation !== generationRef.current || currentThreadRef.current !== threadId) {
        await releaseTarget({ threadId, path: normalizedPath, fence: Number(result?.fence || 0) });
        return {
          threadId, path: normalizedPath, fence: 0, status: 'stale', reason: 'thread_changed',
        };
      }
      return remember({
        threadId,
        path: normalizedPath,
        fence: Number(result?.fence || 0),
        status: Number(result?.fence || 0) ? 'editing' : 'readonly',
        reason: Number(result?.fence || 0) ? '' : 'unavailable',
      });
    } catch (error) {
      if (generation !== generationRef.current || currentThreadRef.current !== threadId) {
        return {
          threadId, path: normalizedPath, fence: 0, status: 'stale', reason: 'thread_changed',
        };
      }
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
    if (active || !leaseRef.current.fence) return;
    release({ reason: 'inactive' });
  }, [active, release]);

  useEffect(() => {
    if (!active || !lease.threadId || !lease.path || !lease.fence) return undefined;
    const timer = window.setInterval(async () => {
      const target = leaseRef.current;
      try {
        const { renewWorkspaceLease } = await import('@api/chat');
        const result = await renewWorkspaceLease(target.threadId, target.path, target.fence, {
          actorSession: actorSessionRef.current,
        });
        if (leaseRef.current.threadId !== target.threadId || leaseRef.current.path !== target.path) return;
        remember({ ...target, fence: Number(result?.fence || target.fence), status: 'editing' });
      } catch {
        if (leaseRef.current.threadId !== target.threadId || leaseRef.current.path !== target.path) return;
        remember({ ...target, fence: 0, status: 'lost', reason: 'expired' });
        notify?.({
          title: 'Право на правку истекло',
          description: 'Текст сохранён в редакторе. Получите право на правку повторно.',
          status: 'warning',
          duration: 4500,
        });
      }
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [active, lease.fence, lease.path, lease.threadId, notify, remember]);

  useEffect(() => () => {
    generationRef.current += 1;
    releaseTarget(leaseRef.current);
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
