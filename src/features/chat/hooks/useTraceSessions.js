import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TRACE_MAX_ITEMS, TRACE_MAX_SESSIONS } from "../constants/limits";
import { clampTraceDetail } from "../utils/trace";

// Монотонный счётчик гарантирует уникальные id (и React-ключи) даже при серии
// событий в одном тике — в отличие от Date.now()+Math.random() (риск коллизий).
let _traceIdSeq = 0;
const nextTraceId = (prefix) => `${prefix}_${Date.now()}_${(_traceIdSeq += 1)}`;

export function useTraceSessions({ showTracePanel }) {
  const [traceSessions, setTraceSessions] = useState([]);
  const [activeTraceSessionId, setActiveTraceSessionId] = useState(null);
  const [tracePanelsExpanded, setTracePanelsExpanded] = useState({});
  const traceSessionsRef = useRef([]);
  const activeTraceSessionIdRef = useRef(null);

  useEffect(() => {
    traceSessionsRef.current = traceSessions;
  }, [traceSessions]);

  useEffect(() => {
    activeTraceSessionIdRef.current = activeTraceSessionId;
  }, [activeTraceSessionId]);

  const createTraceSession = useCallback((title = "Подготовка запроса", anchorMessageId = null) => {
    const sessionId = nextTraceId('trace_session');
    const session = {
      id: sessionId,
      title,
      status: "running",
      startedAt: new Date().toISOString(),
      events: [],
      anchorMessageId,
    };

    setTraceSessions((prev) => [...prev, session].slice(-TRACE_MAX_SESSIONS));
    setTracePanelsExpanded((prev) => ({ ...prev, [sessionId]: true }));
    setActiveTraceSessionId(sessionId);
    activeTraceSessionIdRef.current = sessionId;
    // Ref сессий синхронизируется useEffect'ом, то есть только ПОСЛЕ рендера. Пока он
    // не обновился, ensureTraceSession не находил только что созданную сессию и делал
    // ещё одну — и так на каждое событие в тике. Восемь файлов, загруженных разом,
    // давали восемь СЕССИЙ по одному событию: до сообщения доживала последняя, и в
    // трейсе из восьми файлов оставался один. Дописываем ref сразу.
    traceSessionsRef.current = [...traceSessionsRef.current, session].slice(-TRACE_MAX_SESSIONS);
    return sessionId;
  }, []);

  const ensureTraceSession = useCallback((fallbackTitle = "Подготовка запроса", anchorMessageId = null) => {
    const activeId = activeTraceSessionIdRef.current;
    const activeSession = traceSessionsRef.current.find((session) => session.id === activeId);
    if (activeSession && activeSession.status === "running") {
      return activeSession.id;
    }
    return createTraceSession(fallbackTitle, anchorMessageId);
  }, [createTraceSession]);

  const startTraceSession = useCallback((queryText, anchorMessageId = null) => {
    const sessionId = ensureTraceSession("Подготовка запроса", anchorMessageId);
    setTraceSessions((prev) => prev.map((session) => (
      session.id === sessionId
        ? {
            ...session,
            title: clampTraceDetail(queryText, 96),
            // Полный текст запроса — для контент-ключа персиста трейса (совпадает
            // с бэкендовым feedback_key на переоткрытии треда).
            query: typeof queryText === "string" ? queryText.trim() : "",
            anchorMessageId: anchorMessageId || session.anchorMessageId || null,
            status: "running",
            finishedAt: null,
          }
        : session
    )));
    activeTraceSessionIdRef.current = sessionId;
    setActiveTraceSessionId(sessionId);
    setTracePanelsExpanded((prev) => ({ ...prev, [sessionId]: true }));
    return sessionId;
  }, [ensureTraceSession]);

  const appendTraceEvent = useCallback((event, sessionIdOverride = null) => {
    const sessionId = sessionIdOverride || ensureTraceSession("Подготовка запроса");
    if (!event?.title) {
      return;
    }
    const isThinking = event.kind === "thinking";
    const normalizedEvent = {
      id: nextTraceId('trace'),
      timestamp: event.timestamp || new Date().toISOString(),
      kind: event.kind || "info",
      title: String(event.title),
      // Рассуждения показываем развёрнуто (длиннее, с переносами); прочие
      // детали — компактной однострочкой.
      detail: isThinking ? clampTraceDetail(event.detail, 1600, true) : clampTraceDetail(event.detail),
      // Предложение дорогого режима живёт ШАГОМ ТРЕЙСА, а не карточкой под ответом:
      // решение имеет смысл по ходу работы. Полезная нагрузка (режим, ярлык, серверный
      // `offered_at`) едет как есть — по ней строка рисует отсчёт и кнопку.
      ...(event.offer ? { offer: event.offer } : {}),
    };

    setTraceSessions((prev) => prev.map((session) => {
      if (session.id !== sessionId) return session;
      // 🔴 Событие-ошибка НЕ завершает сессию. Сбой ОДНОГО шага («ссылка недоступна») —
      // не сбой прогона: работа идёт дальше. А статус не-`running` заставлял
      // `ensureTraceSession` начать НОВУЮ карточку, и остальной ход работы уезжал туда —
      // снаружи трейс выглядел замершим на ошибке. Итог сессии подводит только
      // `finalizeTraceSession`; само событие и так рисуется красным по своему `kind`.
      return {
        ...session,
        events: [...session.events, normalizedEvent].slice(-TRACE_MAX_ITEMS),
      };
    }));
  }, [ensureTraceSession]);

  // Прогресс длительного шага (напр. deep research) — обновляем ОДИН прогресс-бар
  // на сессии, а не плодим строки. percent: 0..100|null, label: текст-веха.
  const updateTraceProgress = useCallback((percent, label, sessionIdOverride = null) => {
    const sessionId = sessionIdOverride || ensureTraceSession("Подготовка запроса");
    setTraceSessions((prev) => prev.map((session) => {
      if (session.id !== sessionId) return session;
      const pct = typeof percent === "number" && Number.isFinite(percent)
        ? Math.max(0, Math.min(100, Math.round(percent)))
        : (session.progress?.percent ?? null);
      const nextLabel = clampTraceDetail(label, 120) || session.progress?.label || "Идёт исследование";
      return { ...session, progress: { percent: pct, label: nextLabel } };
    }));
  }, [ensureTraceSession]);

  const markConfirmationAccepted = useCallback(() => {
    setTraceSessions((previous) => {
      let updated = false;
      const next = [...previous];
      for (let sessionIndex = next.length - 1; sessionIndex >= 0 && !updated; sessionIndex -= 1) {
        const session = next[sessionIndex];
        const events = [...(session.events || [])];
        for (let eventIndex = events.length - 1; eventIndex >= 0; eventIndex -= 1) {
          const event = events[eventIndex];
          if (event?.offer?.mode !== "expensive_run" || event.offer.status === "accepted") {
            continue;
          }
          events[eventIndex] = {
            ...event,
            offer: { ...event.offer, status: "accepted", expired: false },
          };
          next[sessionIndex] = { ...session, events };
          updated = true;
          break;
        }
      }
      if (updated) traceSessionsRef.current = next;
      return updated ? next : previous;
    });
  }, []);

  const finalizeTraceSession = useCallback((status = "done", sessionIdOverride = null) => {
    const sessionId = sessionIdOverride || activeTraceSessionIdRef.current;
    if (!sessionId) return;
    const finalizedAt = new Date().toISOString();
    setTraceSessions((prev) => prev.map((session) => {
      if (session.id !== sessionId) return session;
      // 🔴 УСПЕХ ПОБЕЖДАЕТ. Раньше ошибка была «липкой»: обрыв канала помечал сессию
      // провалившейся, ответ приходил резервным путём — и над готовым ответом висело
      // «Не удалось подготовить ответ». Провал — это когда ответа НЕТ; а `done` зовётся
      // ровно тогда, когда ответ собран. Сбой канала при этом не пропадает: он остаётся
      // отдельным событием внутри хода работы.
      const nextStatus = status === "done" || session.status === "done" ? "done" : status;
      // Прогресс-бар живёт только пока идёт исследование — на финале убираем.
      return { ...session, status: nextStatus, progress: null, finishedAt: session.finishedAt || finalizedAt };
    }));
  }, []);

  const traceSessionByAnchor = useMemo(() => {
    const map = new Map();
    traceSessions.forEach((session) => {
      if (session.anchorMessageId) {
        map.set(session.anchorMessageId, session);
      }
    });
    return map;
  }, [traceSessions]);

  const activeOrLatestTraceSession = useMemo(() => {
    if (!showTracePanel || !traceSessions.length) return null;
    const activeSession = activeTraceSessionId
      ? traceSessions.find((session) => session.id === activeTraceSessionId)
      : null;
    return activeSession || traceSessions[traceSessions.length - 1];
  }, [activeTraceSessionId, showTracePanel, traceSessions]);

  // То же, но БЕЗ гейта showTracePanel — для живой строки активности агента,
  // которая должна показывать текущий шаг даже при выключенной трейс-панели.
  const liveTraceSession = useMemo(() => {
    if (!traceSessions.length) return null;
    const activeSession = activeTraceSessionId
      ? traceSessions.find((session) => session.id === activeTraceSessionId)
      : null;
    return activeSession || traceSessions[traceSessions.length - 1];
  }, [activeTraceSessionId, traceSessions]);

  const resetTraceSessions = useCallback(() => {
    traceSessionsRef.current = [];
    activeTraceSessionIdRef.current = null;
    setTraceSessions([]);
    setActiveTraceSessionId(null);
    setTracePanelsExpanded({});
  }, []);

  // Восстановление персиста трейса при переоткрытии треда: добавляем сессии,
  // ре-анкоренные к сообщениям истории (по content-key), не дублируя якоря.
  // Восстановленные панели — свёрнуты (историческое, не отвлекает).
  const restoreSessions = useCallback((sessions) => {
    if (!Array.isArray(sessions) || sessions.length === 0) return;
    setTraceSessions((prev) => {
      const existingAnchors = new Set(prev.map((s) => s.anchorMessageId).filter(Boolean));
      const fresh = sessions.filter((s) => s.anchorMessageId && !existingAnchors.has(s.anchorMessageId));
      if (!fresh.length) return prev;
      return [...fresh, ...prev].slice(-TRACE_MAX_SESSIONS);
    });
    setTracePanelsExpanded((prev) => {
      const next = { ...prev };
      for (const s of sessions) {
        if (s.id && !(s.id in next)) next[s.id] = false;
      }
      return next;
    });
  }, []);

  return {
    traceSessions,
    tracePanelsExpanded,
    setTracePanelsExpanded,
    traceSessionByAnchor,
    activeOrLatestTraceSession,
    liveTraceSession,
    startTraceSession,
    appendTraceEvent,
    updateTraceProgress,
    markConfirmationAccepted,
    finalizeTraceSession,
    resetTraceSessions,
    restoreSessions,
  };
}
