import { useEffect, useMemo, useRef } from 'react';
import { CHAT_UI_CONFIG } from '../../config/uiConfig';
import { feedbackKey } from '../../utils/feedbackKey';
import { useChatAutoScroll } from '../useChatAutoScroll';

function latestProviderStatus(messages) {
  const latestAgentMessage = [...messages]
    .reverse()
    .find((candidate) => candidate?.type === 'agent');
  const metadata = latestAgentMessage?.metadata || {};
  if (metadata.provider_unavailable) {
    return {
      unavailable: true,
      error: typeof metadata.provider_error === 'string' ? metadata.provider_error : '',
    };
  }
  return { unavailable: false, error: '' };
}

function latestModel(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (candidate?.type === 'agent' && candidate?.metadata?.selected_model) {
      return candidate.metadata.selected_model;
    }
  }
  return '';
}

export function useChatMessagePresentation({
  messages,
  isLoading,
  scrollRef,
  showTracePanel,
  traceSessions,
  activeOrLatestTraceSession,
  setTracePanelsExpanded,
  threadId,
  isAuthenticated,
}) {
  const postedTraceRef = useRef(new Set());
  const autoScrollSignal = useMemo(() => {
    const last = messages[messages.length - 1];
    return `${messages.length}:${last?.type || ''}:${last?.content?.length || 0}`;
  }, [messages]);
  const isStreaming = isLoading || Boolean(messages[messages.length - 1]?.isTyping);
  const scroll = useChatAutoScroll({
    scrollRef,
    contentSignal: autoScrollSignal,
    isStreaming,
  });
  const lastUsedModel = useMemo(() => latestModel(messages), [messages]);
  const visibleMessages = useMemo(
    () => messages.filter((message) => {
      if (message.type === 'agent') {
        return message.isTyping
          || message.complete
          || Boolean(message.content && message.content.trim());
      }
      return Boolean(message.content && message.content.trim());
    }),
    [messages],
  );
  const providerStatus = useMemo(() => latestProviderStatus(messages), [messages]);

  useEffect(() => {
    const latestSession = activeOrLatestTraceSession;
    if (!showTracePanel || !traceSessions.length || !latestSession) return undefined;
    if (latestSession.status === 'running') return undefined;
    const collapseTimer = window.setTimeout(() => {
      setTracePanelsExpanded((previous) => ({
        ...previous,
        [latestSession.id]: false,
      }));
    }, CHAT_UI_CONFIG.trace.autoCollapseDelayMs);
    return () => window.clearTimeout(collapseTimer);
  }, [activeOrLatestTraceSession, setTracePanelsExpanded, showTracePanel, traceSessions.length]);

  useEffect(() => {
    if (!threadId || !isAuthenticated) return;
    const pending = traceSessions.filter((session) => (
      session
      && session.status
      && session.status !== 'running'
      && session.query
      && session.events?.length
      && !postedTraceRef.current.has(session.id)
    ));
    pending.forEach((session) => {
      postedTraceRef.current.add(session.id);
      import('@api/chat')
        .then(({ saveThreadTrace }) => (
          saveThreadTrace(threadId, feedbackKey(session.query), session)
        ))
        .catch(() => { /* Trace persistence is intentionally fail-open. */ });
    });
  }, [isAuthenticated, threadId, traceSessions]);

  return {
    ...scroll,
    lastUsedModel,
    visibleMessages,
    providerStatus,
  };
}
