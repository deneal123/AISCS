import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelTask, getTaskStatus } from '@api/jobs';
import { useWorkActionOwner } from '@shared/hooks/useWorkActionOwner';

const IDLE = { phase: 'idle', error: '', terminal: null };

/** Explicit same-child Stop. A cancellation ACK is not a terminal execution fact. */
export function useQuestionContinuationStop({ scopeKey, childId, canStart, onStart }) {
  const key = scopeKey && childId ? `${scopeKey}/stop/${childId}` : null;
  const [stored, setStored] = useState(IDLE);
  const intent = useRef(null);
  const reader = useRef(null);
  const sequence = useRef(0);
  const writing = useRef(null);
  const live = useRef(null);
  live.current = { canStart, onStart };
  const { begin, owns, finish, isCurrent, busy } = useWorkActionOwner({ threadId: key, active: Boolean(key) });
  const state = stored.key === key ? stored : IDLE;
  const isRequested = useCallback(() => Boolean(key && intent.current === key), [key]);
  const invalidate = useCallback(() => { ++sequence.current; reader.current?.abort(); }, []);
  useEffect(() => {
    intent.current = null;
    setStored({ ...IDLE, key });
    return invalidate;
  }, [invalidate, key]);

  const check = useCallback(async () => {
    if (!isCurrent(key) || intent.current !== key) return;
    reader.current?.abort();
    const controller = new AbortController(); reader.current = controller;
    const ticket = ++sequence.current;
    const current = () => isCurrent(key) && intent.current === key
      && ticket === sequence.current && !controller.signal.aborted;
    try {
      const result = await getTaskStatus(childId, { signal: controller.signal, skipRetry: true });
      if (!current()) return;
      if (result?.task_id !== childId) throw new Error('foreign_child');
      if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(result.state)) {
        setStored({ key, phase: 'settled', terminal: result.state, error: '' });
      } else if (['PENDING', 'STARTED', 'RETRY', 'PROGRESS'].includes(result.state)) {
        setStored({ key, phase: 'requested', terminal: null,
          error: 'Остановка ещё не подтверждена. Проверьте состояние продолжения.' });
      } else throw new Error('unknown_child_state');
    } catch {
      if (current()) setStored({ key, phase: 'unknown', terminal: null,
        error: 'Не удалось проверить продолжение. Результат остановки пока неизвестен.' });
    }
  }, [childId, isCurrent, key]);
  const refresh = useCallback(async () => {
    if (writing.current === key) return;
    await check();
  }, [check, key]);
  useEffect(() => {
    if (!isRequested() || state.phase === 'settled') return undefined;
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, [isRequested, refresh, state.phase]);

  const stop = useCallback(async () => {
    if (!isCurrent(key) || live.current.canStart?.() === false || state.phase === 'settled') return;
    const ticket = begin(key, 'stop');
    if (!ticket) return;
    intent.current = key; writing.current = key;
    invalidate(); live.current.onStart?.();
    setStored({ key, phase: 'stopping', terminal: null, error: 'Отправляю запрос остановки…' });
    try {
      const receipt = await cancelTask(childId, { skipRetry: true });
      if (receipt?.task_id !== childId || typeof receipt.cancelled !== 'boolean') throw new Error('invalid_stop_receipt');
    } catch {
      // Lost ACK is reconciled by the same owned task GET, never by a new run.
    }
    try { if (owns(ticket)) await check(); }
    finally { if (writing.current === key) writing.current = null; finish(ticket); }
  }, [begin, check, childId, finish, invalidate, isCurrent, key, owns, state.phase]);
  const requested = stored.key === key && isRequested();
  return { ...state, requested, isRequested, busy, stop, refresh,
    closed: requested && state.phase === 'settled',
    notice: state.terminal === 'SUCCESS' ? 'Продолжение уже завершено. Итог доступен в Чате.'
      : 'Продолжение завершено после запроса остановки. Подробности — в Чате.' };
}
