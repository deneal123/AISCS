import { useCallback, useEffect, useRef, useState } from 'react';
import { feedbackKey } from '../../utils/feedbackKey';

function mapHistoryRows(rows) {
  return rows.map((row, index) => {
    const metadata = row.metadata || null;
    return {
      id: `hist_${index}_${row.created_at || index}`,
      type: row.sender === 'user' ? 'user' : 'agent',
      content: row.content || '',
      timestamp: row.created_at || new Date().toISOString(),
      complete: true,
      isTyping: false,
      typingProgress: 1,
      feedback: row.feedback || null,
      metadata,
      file_url: metadata?.file_url || null,
      attachments: metadata?.attachments || null,
    };
  });
}

function restoreAnchoredTrace(mappedMessages, traceData, restoreSessions) {
  const traceByContent = traceData?.traces || {};
  const restored = mappedMessages.flatMap((message) => {
    if (message.type !== 'user') return [];
    const session = traceByContent[feedbackKey(message.content)];
    return session ? [{ ...session, anchorMessageId: message.id }] : [];
  });
  let anchor = null;
  mappedMessages.forEach((message) => {
    if (message.type === 'user') anchor = message;
    const offer = message.metadata?.mode_offer;
    if (!anchor || !message.metadata?.awaiting_confirmation || !offer?.offer_id) return;
    const index = restored.findIndex((session) => session.anchorMessageId === anchor.id);
    const previous = index >= 0 ? restored[index] : {
      id: `confirmation_${offer.offer_id}`, anchorMessageId: anchor.id,
      query: anchor.content, startedAt: message.timestamp, events: [],
    };
    const events = (previous.events || []).filter((event) => !event.offer);
    events.push({ id: `offer_${offer.offer_id}`, kind: 'offer', title: 'Нужно ваше решение', offer });
    const session = { ...previous, events, status: offer.status === 'pending' && !offer.expired
      ? 'awaiting_confirmation' : 'done' };
    if (index >= 0) restored[index] = session;
    else restored.push(session);
  });
  if (restored.length) restoreSessions(restored);
}

/** Owns thread-change reset, persisted history and trace restoration. */
export function useChatHistoryLifecycle({
  routeThreadId,
  initialMessage,
  isAuthenticated,
  showTracePanel,
  clearThread,
  loadHistory,
  restoreSessions,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const didMountThreadRef = useRef(false);
  const reload = useCallback(() => setReloadNonce((value) => value + 1), []);

  useEffect(() => {
    if (didMountThreadRef.current) clearThread();
    else didMountThreadRef.current = true;
  }, [clearThread, routeThreadId]);

  useEffect(() => {
    if (!routeThreadId || initialMessage || !isAuthenticated) return undefined;
    let cancelled = false;
    setLoading(true);
    setError(false);

    const fetchHistory = async () => {
      try {
        const { getChatHistory, getThreadTrace } = await import('@api/chat');
        const [data, traceData] = await Promise.all([
          getChatHistory(routeThreadId, 100),
          showTracePanel
            ? getThreadTrace(routeThreadId).catch(() => null)
            : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const rows = Array.isArray(data?.messages) ? data.messages : [];
        if (!rows.length) return;
        const mapped = mapHistoryRows(rows);
        loadHistory(mapped);
        restoreAnchoredTrace(mapped, traceData, restoreSessions);
      } catch (requestError) {
        const status = requestError?.status ?? requestError?.response?.status;
        if (!cancelled && status !== 404) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchHistory();
    return () => { cancelled = true; };
  }, [
    initialMessage,
    isAuthenticated,
    loadHistory,
    reloadNonce,
    restoreSessions,
    routeThreadId,
    showTracePanel,
  ]);

  return { loading, error, reload };
}
