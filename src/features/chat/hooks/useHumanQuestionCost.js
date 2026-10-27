import { useCallback, useEffect, useRef, useState } from 'react';
import { decideHumanQuestionCost, readHumanQuestionCost } from '@api/humanQuestions';
import { useWorkActionOwner } from '@shared/hooks/useWorkActionOwner';
import { parseHumanQuestionCost } from '../model/humanQuestionCost';
import { useQuestionContinuationStop } from './useQuestionContinuationStop';

const EMPTY = { view: null, phase: 'cost_loading', error: '' };

/** Same-child consent. Focus, expiry and recovery only read; no passive POST. */
export function useHumanQuestionCost({ threadId, scopeKey, question, active }) {
  const key = active && question?.state === 'accepted' ? `${scopeKey}/${question.resume_job_id}` : null;
  const [stored, setStored] = useState(EMPTY);
  const attempt = useRef(null);
  const reader = useRef(null);
  const sequence = useRef(0);
  const writing = useRef(null);
  const owner = useWorkActionOwner({ threadId: key, active: Boolean(key) });
  const { isCurrent } = owner;
  const live = useRef(null);
  const state = stored.key === key ? stored : EMPTY;
  live.current = { key, question, state, busy: owner.busy };
  const current = useCallback(expected => Boolean(isCurrent(expected) && live.current.key === expected), [isCurrent]);
  const invalidateRead = useCallback(() => { ++sequence.current; reader.current?.abort(); }, []);
  const stop = useQuestionContinuationStop({ scopeKey: key, childId: question?.resume_job_id,
    canStart: () => writing.current !== key, onStart: invalidateRead });
  const { isRequested: stopRequested, refresh: checkStop } = stop;
  const apply = useCallback((expected, raw) => {
    if (!current(expected) || stopRequested()) return;
    const view = parseHumanQuestionCost(raw);
    if (attempt.current?.key === expected && (attempt.current.payload.offer_id !== view.offer_id
      || !['pending', 'expired'].includes(view.state)
      || (view.state === 'expired' && attempt.current.payload.decision === 'accept'))) attempt.current = null;
    setStored({ key: expected, view, phase: `cost_${view.state}`, error: '' });
  }, [current, stopRequested]);
  const refresh = useCallback(async () => {
    if (stopRequested()) { await checkStop(); return; }
    if (!current(key) || live.current.busy || writing.current === key) return;
    reader.current?.abort();
    const controller = new AbortController(); reader.current = controller;
    const ticket = ++sequence.current;
    try {
      const raw = await readHumanQuestionCost(threadId, live.current.question, controller.signal);
      if (ticket === sequence.current && !controller.signal.aborted) apply(key, raw);
    } catch {
      if (!controller.signal.aborted && ticket === sequence.current && current(key)) {
        setStored(previous => ({ ...(previous.key === key ? previous : EMPTY), key, phase: 'cost_unavailable',
          error: 'Не удалось проверить стоимость продолжения. Проверьте состояние перед повтором.' }));
      }
    }
  }, [apply, checkStop, current, key, stopRequested, threadId]);
  useEffect(() => {
    invalidateRead();
    setStored({ ...EMPTY, key });
    if (attempt.current?.key !== key) attempt.current = null;
    if (key) refresh();
    return invalidateRead;
  }, [key, refresh, invalidateRead]);
  useEffect(() => {
    if (!key || ['accepted', 'not_required', 'declined', 'cancelled'].includes(state.view?.state)) return undefined;
    const focus = () => refresh();
    window.addEventListener('focus', focus);
    const remaining = state.view?.state === 'pending' ? Date.parse(state.view.expires_at) - Date.now() : NaN;
    const timer = Number.isFinite(remaining) ? setTimeout(focus, Math.max(0, Math.min(remaining + 100, 2147483647))) : null;
    return () => { window.removeEventListener('focus', focus); if (timer) clearTimeout(timer); };
  }, [key, refresh, state.view?.offer_id, state.view?.state, state.view?.expires_at]);

  const decide = useCallback(async decision => {
    if (stopRequested() || !current(key) || !['cost_pending', 'cost_expired', 'cost_blocked'].includes(live.current.state.phase)) return;
    const view = live.current.state.view;
    const prior = attempt.current?.key === key ? attempt.current.payload : null;
    if (!view || !['accept', 'decline', 'refresh'].includes(decision)
      || (live.current.state.phase === 'cost_blocked' && decision !== 'decline')
      || (prior && prior.decision !== decision)
      || (decision === 'accept' && view.state !== 'pending')
      || (decision === 'refresh' && view.state !== 'expired')) return;
    const ticket = owner.begin(key, decision);
    if (!ticket) return;
    const payload = prior || { offer_id: view.offer_id, decision };
    attempt.current = { key, payload }; writing.current = key;
    ++sequence.current; reader.current?.abort();
    try {
      const raw = await decideHumanQuestionCost(threadId, live.current.question, payload);
      if (owner.owns(ticket) && current(key)) { ++sequence.current; apply(key, raw); }
    } catch (error) {
      if (owner.owns(ticket) && current(key)) {
        const code = error?.response?.data?.detail?.code;
        if (error?.response?.status === 409 && ['human_question_binding_changed', 'source_changed', 'ide_generation_changed'].includes(code)) {
          attempt.current = null;
          setStored(previous => ({ ...previous, phase: 'cost_blocked', error: 'Проект изменился. Вернитесь к исходному проекту или отмените продолжение.' }));
        } else setStored(previous => ({ ...previous, phase: 'cost_unknown',
          error: 'Результат решения пока неизвестен. Проверьте состояние — повторный запуск не нужен.' }));
      }
    } finally { if (writing.current === key) writing.current = null; owner.finish(ticket); }
  }, [apply, current, key, owner, stopRequested, threadId]);
  const ready = !stop.requested && ['accepted', 'not_required'].includes(state.view?.state)
    && !['cost_unavailable', 'cost_unknown'].includes(state.phase);
  const closed = stop.closed || ['cost_declined', 'cost_cancelled'].includes(state.phase);
  return { ...state, phase: stop.requested ? stop.closed ? 'cost_stopped' : `cost_stop_${stop.phase}` : state.phase,
    error: stop.requested ? stop.error : state.error, stop, ready, closed, busy: owner.busy || stop.busy, refresh, decide,
    retry: attempt.current?.key === key ? attempt.current.payload.decision : null };
}
