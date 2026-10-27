import { useEffect, useState } from 'react';
import { secondsLeftOf } from '../components/ModeOffer';
import { presentTaskResult } from '../model/taskResult';
import { latestReplyAfterAnchor, latestTimelineMessage } from '../utils/latestTimelineMessage';

/** Presentation only: observes the existing anchored run, never admits/retries work. */
export function useDocumentAssistant(messages = {}) {
  const { visibleMessages = [], traceSessionByAnchor, activeTraceSession, isLoading } = messages;
  const anchor = latestTimelineMessage(visibleMessages, message => message.type === 'user') || undefined;
  const session = anchor && (activeTraceSession?.anchorMessageId === anchor.id
    ? activeTraceSession : traceSessionByAnchor?.get(anchor.id));
  const reply = latestReplyAfterAnchor(visibleMessages, anchor);
  const taskResult = presentTaskResult(reply?.metadata?.task_result);
  const offer = session?.status === 'awaiting_confirmation'
    ? [...(session.events || [])].reverse().find((event) => event.offer)?.offer : null;
  const [now, setNow] = useState(Date.now);
  const unresolved = offer && !offer.expired && !['accepted', 'declined'].includes(offer.status);
  const waiting = Boolean(unresolved && secondsLeftOf(offer, now) > 0);
  useEffect(() => {
    setNow(Date.now());
    if (!unresolved || !waiting) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [unresolved, waiting, offer?.offer_id, offer?.offered_at]);
  return { anchor, session, taskResult, running: Boolean(isLoading), waiting,
    tracing: Boolean(isLoading || waiting),
    expired: Boolean(offer && !['accepted', 'declined'].includes(offer.status)
      && (offer.expired || secondsLeftOf(offer, now) <= 0)) };
}
