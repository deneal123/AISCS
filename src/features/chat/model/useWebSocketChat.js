import { useState, useEffect, useRef, useCallback } from 'react';
import { useAppToast } from '@shared/hooks/useAppToast';
import { protocolError, safeErrorMessage, validateWsFrame } from './wsProtocol';

const MAX_RECONNECT_ATTEMPTS = 5;
const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;
const HEARTBEAT_TIMEOUT_MS = 30000;
const HEARTBEAT_CHECK_INTERVAL_MS = 10000;

function buildWsUrl(threadId, lastId) {
  const rawBase =
    process.env.REACT_APP_WS_BASE_URL ||
    process.env.REACT_APP_API_BASE_URL ||
    '';

  let base = rawBase.trim().replace(/\/$/, '');
  if (!base) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${proto}//${window.location.host}`;
  } else if (base.startsWith('http://')) {
    base = `ws://${base.slice(7)}`;
  } else if (base.startsWith('https://')) {
    base = `wss://${base.slice(8)}`;
  }

  const params = lastId ? `?last_id=${encodeURIComponent(lastId)}` : '';
  return `${base}/api/chats/${threadId}/ws${params}`;
}

/**
 * Чистый WS-транспорт чата: соединение + отправка + отмена + форвардинг событий
 * через колбэки. Стор сообщений живёт в редьюсере (useChatDomainState), наполняемом
 * через useChatStreamingLifecycle — здесь мы НЕ дублируем список сообщений, чтобы не
 * плодить setState на каждый стрим-чанк и не держать два конкурирующих источника истины.
 */
export function useWebSocketChat(threadId, callbacks = {}) {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState('disconnected');
  const [lastHeartbeat, setLastHeartbeat] = useState(null);

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY_MS);
  const connectingRef = useRef(false);
  const currentThreadIdRef = useRef(threadId);
  const prevThreadIdRef = useRef(null);
  const messageQueueRef = useRef([]);
  const lastIdRef = useRef(null);
  const heartbeatCheckRef = useRef(null);
  const connectRef = useRef(null);

  const toast = useAppToast();

  const {
    onJobCreated,
    onComplete,
    onError,
    onConnect,
    onDisconnect,
    onAgentReply,
    onStreamChunk,
    onAgentComplete,
    onAgentEvent,
  } = callbacks;

  const scheduleReconnect = useCallback(() => {
    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      toast({ title: 'Соединение потеряно', description: 'Не удалось восстановить соединение с чатом.', status: 'warning', duration: 10000 });
      return;
    }
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    reconnectAttemptsRef.current += 1;
    const delay = reconnectDelayRef.current;
    reconnectDelayRef.current = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
    reconnectTimeoutRef.current = setTimeout(() => connectRef.current?.(), delay);
  }, [toast]);

  const handleIncomingMessage = useCallback((data, _depth = 0) => {
    const eventType = data.type || data.event;

    switch (eventType) {
      case 'replay':
      case 'claimed': {
        // Deliver replayed/claimed stream entries as messages (depth guard: max 1 level)
        if (_depth < 1) {
          const inner = data.data || {};
          const innerType = inner.type || inner.event;
          if (innerType) {
            handleIncomingMessage({ ...inner }, _depth + 1);
          }
        }
        break;
      }

      case 'heartbeat':
        setLastHeartbeat(Date.now());
        break;

      case 'job_created':
        // Единый источник job-состояния — reducer (useChatStreamingLifecycle.onJobCreated
        // кладёт туда id + celeryTaskId из этого же события). Здесь только форвардим.
        onJobCreated?.(data);
        break;

      case 'stream_chunk':
        onStreamChunk?.(data);
        break;

      case 'agent_reply':
        onAgentReply?.(data);
        break;

      case 'agent_complete':
        onAgentComplete?.(data);
        onComplete?.(data);
        break;

      case 'error': {
        // ⚠️ Форм у ошибки ДВЕ, и раньше читалась только одна. Бэкенд шлёт свои ошибки
        // с полем `error`, а ошибки агент-сайдкара приезжают как `data`/`message`
        // (см. contracts/events.py) — эта ветка их не разбирала, поэтому на ЛЮБОЙ сбой
        // агента пользователь видел «Неизвестная ошибка». Готовый человеческий текст
        // («превышено время ожидания», «слишком много запросов») доезжал до браузера и
        // молча выбрасывался.
        const errorText = safeErrorMessage(data);
        onError?.(new Error(errorText));
        toast({ title: 'Ошибка', description: errorText, status: 'error', duration: 5000 });
        break;
      }

      default:
        // Forward all agent lifecycle events (routing_start, routing_complete,
        // agent_start, agent_complete, tool_call_start, tool_call_complete, etc.)
        onAgentEvent?.(data);
        break;
    }
  }, [onJobCreated, onComplete, onError, onAgentReply, onStreamChunk, onAgentComplete, onAgentEvent, toast]);

  const connect = useCallback(() => {
    if (connectingRef.current || !threadId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return;

    connectingRef.current = true;
    setConnectionState('connecting');

    const capturedThreadId = threadId;
    currentThreadIdRef.current = threadId;
    setTimeout(() => {
      if (!connectingRef.current || currentThreadIdRef.current !== capturedThreadId) return;
      let wsUrl;
      try {
        wsUrl = buildWsUrl(threadId, lastIdRef.current);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setIsConnected(true);
          setConnectionState('connected');
          reconnectAttemptsRef.current = 0;
          reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;
          connectingRef.current = false;
          onConnect?.(threadId);
          messageQueueRef.current.forEach((msg) => {
            try { ws.send(JSON.stringify(msg)); } catch (_) {}
          });
          messageQueueRef.current = [];
        };

        ws.onmessage = (event) => {
          try {
            const decoded = JSON.parse(event.data);
            const validation = validateWsFrame(decoded);
            if (!validation.ok) {
              onAgentEvent?.(protocolError(validation.eventType, validation.reason));
              return;
            }
            const data = validation.frame;
            if (data.id) lastIdRef.current = data.id;
            handleIncomingMessage(data);
          } catch (_) {
            onAgentEvent?.(protocolError('', 'invalid_json'));
          }
        };

        ws.onclose = (event) => {
          setIsConnected(false);
          setConnectionState('disconnected');
          setLastHeartbeat(null);
          connectingRef.current = false;
          if (heartbeatCheckRef.current) {
            clearInterval(heartbeatCheckRef.current);
            heartbeatCheckRef.current = null;
          }
          // Восстановимый разрыв (код != 1000 и попытки не исчерпаны) → сейчас
          // переподключимся: сообщаем это onDisconnect, чтобы он НЕ гасил live-job
          // (серверная задача жива, после реконнекта stream_chunk реиграются). При
          // исчерпании попыток willReconnect=false → потребитель гасит состояние.
          const willReconnect =
            event.code !== 1000 && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS;
          onDisconnect?.(event, willReconnect);
          if (willReconnect) {
            scheduleReconnect();
          }
        };

        ws.onerror = () => {
          setConnectionState('error');
          connectingRef.current = false;
          onError?.(new Error('WebSocket connection error'));
        };
      } catch (err) {
        setConnectionState('error');
        connectingRef.current = false;
        onError?.(err);
      }
    }, 50);
  }, [threadId, handleIncomingMessage, onConnect, onDisconnect, onError, onAgentEvent, scheduleReconnect]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const sendMessage = useCallback((text, selectedModel = null, inputType = null, options = {}) => {
    if (!text?.trim() && !options.confirmOfferId) return;

    const payload = {
      type: 'message',
      text: text.trim(),
      id: `msg_${Date.now()}_${Math.random()}`,
      timestamp: new Date().toISOString(),
      ...(selectedModel && { model: selectedModel }),
      ...(inputType && { input_type: inputType }),
      ...(options.webSearch && { web_search: true }),
      ...(options.deepResearch && { deep_research: true }),
      ...(options.multiIntent && { multi_intent: true }),
      ...(options.planning && { planning: true }),
      ...(options.personaIds?.length && { persona_ids: options.personaIds }),
      ...(options.memoryEnabled === false && { memory_enabled: false }),
      ...(options.ldrModel && { ldr_model: options.ldrModel }),
      ...(options.ldrStrategy && { ldr_strategy: options.ldrStrategy }),
      ...(options.fileContext && { file_context: options.fileContext }),
      ...(Array.isArray(options.fileIds) && options.fileIds.length && { file_ids: options.fileIds }),
      ...(options.routeOverride && { route_override: options.routeOverride }),
      ...(Array.isArray(options.attachments) && options.attachments.length && { attachments: options.attachments }),
      ...(options.detachFiles && { detach_files: true }),
      // Согласие на дорогой просмотр — признак ЭТОГО сообщения, как detach_files.
      ...(options.watchVideo && { watch_video: true }),
      ...(options.confirmExpensiveRun && { confirm_expensive_run: true }),
      ...(options.confirmOfferId && { confirm_offer_id: options.confirmOfferId }),
    };

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try { wsRef.current.send(JSON.stringify(payload)); }
      catch (err) { messageQueueRef.current.push(payload); onError?.(err); }
    } else {
      messageQueueRef.current.push(payload);
    }
  }, [onError]);

  // Управляющий фрейм (не сообщение) — напр. ручная компактизация контекста.
  // В обход text-guard sendMessage; шлём только если сокет открыт (не копим в очередь).
  const sendControl = useCallback((type, extra = {}) => {
    if (!type || wsRef.current?.readyState !== WebSocket.OPEN) return false;
    try {
      wsRef.current.send(JSON.stringify({ type, id: `ctl_${Date.now()}`, timestamp: new Date().toISOString(), ...extra }));
      return true;
    } catch (_) {
      return false;
    }
  }, []);

  const cancelJob = useCallback(async (celeryTaskId) => {
    // Отменяем по celery-task-id (тот же ключ, которым воркер опрашивает
    // chat:cancel:{id}). Локальный job-стейт гасит вызывающий (reducer) — здесь
    // только сетевой вызов, без второй копии состояния.
    if (!celeryTaskId) return;
    try {
      const { cancelTask } = await import('@api/jobs');
      await cancelTask(celeryTaskId);
    } catch (_) {
      // задача могла уже завершиться — reducer всё равно очистит состояние
    }
  }, []);

  // Auto-connect and cleanup when threadId changes
  useEffect(() => {
    const threadChanged = prevThreadIdRef.current !== threadId;
    if (threadId && threadChanged) {
      currentThreadIdRef.current = threadId;
      messageQueueRef.current = [];
      connectingRef.current = false;
      setConnectionState('disconnected');
      setIsConnected(false);
      connectRef.current?.();
    }
    prevThreadIdRef.current = threadId;

    return () => {
      wsRef.current?.close(1000, 'Thread ID changed');
      wsRef.current = null;
      connectingRef.current = false;
      setConnectionState('disconnected');
      setIsConnected(false);
      setLastHeartbeat(null);
    };
  }, [threadId]);

  // Heartbeat monitoring
  useEffect(() => {
    if (connectionState !== 'connected' || !lastHeartbeat) return;
    heartbeatCheckRef.current = setInterval(() => {
      if (Date.now() - lastHeartbeat > HEARTBEAT_TIMEOUT_MS) {
        setConnectionState('error');
        // The socket may still report readyState OPEN even though the peer/proxy
        // silently dropped it (zombie connection) — close it first so connect()'s
        // OPEN-state guard doesn't turn scheduleReconnect() into a permanent no-op.
        wsRef.current?.close(4000, 'Heartbeat timeout');
        wsRef.current = null;
        scheduleReconnect();
      }
    }, HEARTBEAT_CHECK_INTERVAL_MS);
    return () => {
      clearInterval(heartbeatCheckRef.current);
      heartbeatCheckRef.current = null;
    };
  }, [connectionState, lastHeartbeat, scheduleReconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close(1000, 'Component unmount');
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (heartbeatCheckRef.current) clearInterval(heartbeatCheckRef.current);
      connectingRef.current = false;
    };
  }, []);

  return {
    isConnected,
    connectionState,
    reconnectAttempts: reconnectAttemptsRef.current,
    sendMessage,
    sendControl,
    cancelJob,
  };
}
