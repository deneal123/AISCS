import { useMemo } from 'react';
import { useWebSocketChat } from '../model/useWebSocketChat';

export function useChatTransport({ threadId, callbacks }) {
  const wsCallbacks = useMemo(() => ({
    onMessage: () => {},
    ...callbacks,
  }), [callbacks]);

  const transport = useWebSocketChat(threadId, wsCallbacks);

  return {
    isConnected: transport.isConnected,
    connectionState: transport.connectionState,
    sendMessage: transport.sendMessage,
    sendControl: transport.sendControl,
    cancelJob: transport.cancelJob,
    useWebSocket: transport.isConnected && transport.connectionState === 'connected',
  };
}
