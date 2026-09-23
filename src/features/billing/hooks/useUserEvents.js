import { useEffect, useRef } from 'react';

/**
 * Персональный WS-канал пользователя: слушает лёгкие сигналы вида «перезапроси X».
 *
 * ⚠️ ЗАЧЕМ. Баланс кредитов бэкенд не кэширует — читается живьём из БД. Но фронт
 * перезапрашивал его только при старте, после ответа модели и при возврате на вкладку.
 * Пополнение админом происходит ВНЕ сессии пользователя, и ни одно из этих событий его
 * не триггерит. Чат-WS привязан к job_id и живёт лишь во время запроса — туда не
 * доставить. Этот канал (`/api/users/me/events/ws`) держится, пока открыта вкладка, и
 * приносит сигнал, по которому мы дёргаем reload.
 *
 * НЕ несёт бизнес-данных: по событию `balance_refresh` вызываем onBalanceRefresh, а
 * значение всегда тянем отдельным GET. Поэтому потеря сообщения не страшна — при
 * следующем открытии баланс и так перечитается.
 */

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

function buildUserEventsUrl() {
  const rawBase =
    process.env.REACT_APP_WS_BASE_URL || process.env.REACT_APP_API_BASE_URL || '';
  let base = rawBase.trim().replace(/\/$/, '');
  if (!base) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${proto}//${window.location.host}`;
  } else if (base.startsWith('http://')) {
    base = `ws://${base.slice(7)}`;
  } else if (base.startsWith('https://')) {
    base = `wss://${base.slice(8)}`;
  }
  return `${base}/api/users/me/events/ws`;
}

export function useUserEvents({ enabled = true, onBalanceRefresh } = {}) {
  // Колбэк держим в ref: иначе его смена пересоздавала бы соединение на каждый рендер.
  const handlerRef = useRef(onBalanceRefresh);
  handlerRef.current = onBalanceRefresh;

  useEffect(() => {
    if (!enabled) return undefined;

    let ws = null;
    let reconnectTimer = null;
    let reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
    let closedByUs = false;

    const connect = () => {
      try {
        ws = new WebSocket(buildUserEventsUrl());
      } catch {
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        reconnectDelay = INITIAL_RECONNECT_DELAY_MS; // успех сбрасывает backoff
      };

      ws.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg?.type === 'balance_refresh') {
          handlerRef.current?.();
        }
        // 'heartbeat' и прочее просто игнорируем — соединение живо.
      };

      ws.onclose = () => {
        if (!closedByUs) scheduleReconnect();
      };

      // onerror ведёт к onclose — реконнект там, чтобы не удваивать таймеры.
      ws.onerror = () => {};
    };

    const scheduleReconnect = () => {
      if (closedByUs) return;
      reconnectTimer = setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
    };

    connect();

    return () => {
      closedByUs = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        try {
          ws.close();
        } catch {
          /* уже закрыт */
        }
      }
    };
  }, [enabled]);
}
