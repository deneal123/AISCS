import { useEffect } from 'react';

export function useChatThreadRouting({
  routeThreadId,
  initialMessage,
  threadId,
  search = '',
  navigate,
}) {
  useEffect(() => {
    if (!routeThreadId && !initialMessage && threadId) {
      navigate(`/chat/${threadId}${search}`, { replace: true });
    }
  }, [routeThreadId, initialMessage, threadId, search, navigate]);

  return {
    state: {
      hasRouteThreadId: Boolean(routeThreadId),
    },
    actions: {},
  };
}
