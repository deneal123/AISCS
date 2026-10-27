import { useCallback, useEffect, useRef } from 'react';

export function useChatThreadRouting({
  routeThreadId,
  initialMessage,
  threadId,
  search = '',
  navigate,
  startFreshThread,
}) {
  const unavailableRef = useRef('');
  const handleUnavailableThread = useCallback((unavailableId) => {
    if (!startFreshThread || unavailableId !== threadId || unavailableRef.current === unavailableId) return;
    unavailableRef.current = unavailableId;
    const surface = new URLSearchParams(search).get('surface');
    const nextSearch = ['pdf', 'work'].includes(surface) ? `?surface=${surface}` : '';
    navigate(`/chat/${startFreshThread()}${nextSearch}`, { replace: true });
  }, [threadId, search, navigate, startFreshThread]);
  useEffect(() => {
    if (!routeThreadId && !initialMessage && threadId) {
      navigate(`/chat/${threadId}${search}`, { replace: true });
    }
  }, [routeThreadId, initialMessage, threadId, search, navigate]);

  return {
    state: {
      hasRouteThreadId: Boolean(routeThreadId),
    },
    actions: { handleUnavailableThread },
  };
}
