import { useCallback, useEffect, useRef, useState } from 'react';
import { answerHumanQuestion, cancelHumanQuestion, readHumanQuestion } from '@api/humanQuestions';
import { getTaskStatus } from '@api/jobs';
import { useWorkActionOwner } from '@shared/hooks/useWorkActionOwner';
import { createIntentId } from '@shared/utils/createIntentId';
import { humanQuestionTarget, latestHumanQuestion, questionFailure, sameHumanQuestion } from '../model/humanQuestion';
import { useHumanQuestionCost } from './useHumanQuestionCost';

const EMPTY = { question: null, phase: 'idle', error: '', verified: false };
const TERMINAL = new Set(['SUCCESS', 'FAILURE', 'REVOKED']);

/** One answer owner for both workbench docks; reads never resume or allocate work. */
export function useHumanQuestion({ threadId, accountId, surface, messages = [], context, active, onAccepted, onSettled }) {
  const snapshot = latestHumanQuestion(messages, surface);
  const cacheOwner = `${accountId}/${threadId}`;
  const key = snapshot && `${cacheOwner}/${surface}/${snapshot.question_id}`;
  const [stored, setStored] = useState(EMPTY);
  const [draft, setDraft] = useState({ choice: null, text: '' });
  const memory = useRef({ cacheOwner, drafts: new Map(), attempts: new Map(), announced: new Set() });
  if (memory.current.cacheOwner !== cacheOwner) memory.current = { cacheOwner, drafts: new Map(), attempts: new Map(), announced: new Set() };
  const owner = useWorkActionOwner({ threadId: key, active: Boolean(active && key) });
  const { isCurrent } = owner;
  const live = useRef(null);
  const sequence = useRef(0);
  const reader = useRef(null);
  const writing = useRef(null);
  live.current = { key, active, snapshot, context, onAccepted, onSettled };
  const current = useCallback(expected => Boolean(isCurrent(expected) && live.current.key === expected && live.current.active), [isCurrent]);
  const invalidateRead = useCallback(() => { ++sequence.current; reader.current?.abort(); }, []);
  const state = stored.key === key ? stored : { ...EMPTY, question: snapshot, phase: key ? 'loading' : 'idle' };
  live.current.phase = state.phase;

  const acceptView = useCallback((expected, raw) => {
    if (!current(expected)) return false;
    const question = sameHumanQuestion(live.current.snapshot, raw);
    if (!question) throw new Error('question_protocol');
    setStored({ key: expected, question, phase: question.state, error: '', verified: true });
    if (question.state !== 'pending') memory.current.attempts.delete(expected);
    return true;
  }, [current]);

  const refresh = useCallback(async () => {
    if (!current(key) || owner.busy || writing.current?.key === key) return;
    reader.current?.abort();
    const controller = new AbortController(); reader.current = controller;
    const ticket = ++sequence.current;
    try {
      const raw = await readHumanQuestion(threadId, live.current.snapshot, controller.signal);
      if (ticket !== sequence.current || !current(key)) return;
      acceptView(key, raw);
    } catch (error) {
      if (controller.signal.aborted || ticket !== sequence.current || !current(key)) return;
      setStored(previous => ({ ...previous, key, question: live.current.snapshot, phase: 'unavailable',
        verified: previous.key === key && previous.verified, error: questionFailure(error) }));
    }
  }, [acceptView, current, key, owner.busy, threadId]);

  useEffect(() => {
    invalidateRead();
    setStored({ ...EMPTY, key, question: snapshot, phase: key ? 'loading' : 'idle' });
    setDraft(memory.current.drafts.get(key) || { choice: null, text: '' });
    if (active && key) refresh();
    return invalidateRead;
    // Identity, not every replayed metadata object, owns the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, active, invalidateRead]);

  useEffect(() => {
    if (!active || !key || state.question?.state !== 'pending') return undefined;
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    const remaining = Date.parse(state.question.expires_at) - Date.now();
    const timer = remaining > 0 ? setTimeout(onFocus, Math.min(remaining + 100, 2147483647)) : null;
    return () => { window.removeEventListener('focus', onFocus); if (timer) clearTimeout(timer); };
  }, [active, key, refresh, state.question?.state, state.question?.expires_at]);

  const cost = useHumanQuestionCost({ threadId, scopeKey: key, question: state.question, active: Boolean(active && key && state.verified) });
  const child = cost.ready && state.question?.state === 'accepted' ? state.question.resume_job_id : null;
  useEffect(() => {
    if (child && current(key) && !memory.current.announced.has(child)) {
      memory.current.announced.add(child);
      live.current.onAccepted?.(state.question);
    }
  }, [child, current, key, state.question]);
  const [pollVersion, setPollVersion] = useState(0);
  useEffect(() => {
    if (!active || !child || !key) return undefined;
    const controller = new AbortController();
    let timer; let failures = 0;
    const poll = async () => {
      try {
        const result = await getTaskStatus(child, { signal: controller.signal });
        if (controller.signal.aborted || !current(key)) return;
        if (result?.task_id !== child) throw new Error('foreign_task_status');
        if (TERMINAL.has(result.state)) {
          setStored(previous => ({ ...previous, phase: 'settled', error: '' }));
          live.current.onSettled?.(child, result.state);
          return;
        }
        if (!['PENDING', 'STARTED', 'RETRY', 'PROGRESS'].includes(result.state)) throw new Error('unknown_task_state');
        failures = 0;
        setStored(previous => previous.phase === 'child_unavailable' ? { ...previous, phase: 'accepted', error: '' } : previous);
        timer = setTimeout(poll, 2000);
      } catch {
        if (controller.signal.aborted || !current(key)) return;
        failures += 1;
        if (failures < 3) timer = setTimeout(poll, 2000);
        else setStored(previous => ({ ...previous, phase: 'child_unavailable', error: 'Не удалось проверить продолжение. Повторно запускать запрос не нужно.' }));
      }
    };
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [active, child, current, key, pollVersion]);

  const edit = useCallback(update => {
    if (!current(key) || owner.busy || memory.current.attempts.has(key)) return;
    setDraft(previous => { const next = { ...previous, ...update }; memory.current.drafts.set(key, next); return next; });
  }, [current, key, owner.busy]);

  const mutate = useCallback(async cancel => {
    if (!current(key) || (!cancel && live.current.phase !== 'pending')) return;
    const ticket = owner.begin(key, cancel ? 'cancel' : 'answer');
    if (!ticket) return;
    writing.current = { key, ticket };
    ++sequence.current; reader.current?.abort();
    try {
      let payload = memory.current.attempts.get(key);
      if (!cancel && !payload) {
        const target = humanQuestionTarget(live.current.snapshot, live.current.context);
        if (!target || (!draft.choice && !draft.text.trim())) return;
        payload = { intent_id: createIntentId(), surface, ...target,
          answer: { choice_id: draft.choice, text: draft.text.trim() || null } };
        memory.current.attempts.set(key, payload);
      }
      const raw = await (cancel ? cancelHumanQuestion(threadId, live.current.snapshot)
        : answerHumanQuestion(threadId, live.current.snapshot, payload));
      if (owner.owns(ticket) && current(key)) { ++sequence.current; acceptView(key, raw); }
    } catch (error) {
      if (!owner.owns(ticket) || !current(key)) return;
      setStored(previous => ({ ...previous, key, question: live.current.snapshot, phase: 'unknown', error: questionFailure(error) }));
    } finally { if (writing.current?.ticket === ticket) writing.current = null; owner.finish(ticket); }
  }, [acceptView, current, draft, key, owner, surface, threadId]);

  const locked = Boolean(owner.busy || memory.current.attempts.has(key));
  const costMode = state.verified && state.question?.state === 'accepted' && !cost.ready && !cost.closed;
  const phase = state.verified && state.question?.state === 'accepted' && !cost.ready ? cost.phase : state.phase;
  const blocking = Boolean(active && key && !['accepted', 'settled', 'cancelled', 'expired', 'cost_declined', 'cost_cancelled', 'cost_stopped'].includes(phase));
  const notice = cost.stop.closed ? cost.stop.notice : cost.closed ? 'Платное продолжение отменено. Агент не продолжал работу.'
    : state.phase === 'expired' ? 'Срок вопроса истёк. Агент не продолжал работу.'
    : state.phase === 'cancelled' ? 'Вопрос отменён. Агент не продолжал работу.'
      : state.phase === 'settled' ? 'Продолжение завершено. Итог доступен в Чате.' : '';
  return { ...state, phase, cost, costMode, draft, locked, blocking, notice, busy: owner.busy, retrying: memory.current.attempts.has(key),
    targetReady: Boolean(humanQuestionTarget(snapshot, context)),
    setChoice: choice => edit({ choice: draft.choice === choice ? null : choice }),
    setText: text => edit({ text }), submit: () => mutate(false), cancel: () => mutate(true), refresh,
    checkChild: () => setPollVersion(value => value + 1) };
}
