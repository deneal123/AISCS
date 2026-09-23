import { useCallback, useEffect, useState } from "react";
import { useAppToast } from "@shared/hooks/useAppToast";

export function useRecentThreads({
  navigate,
  resolveSessionUserId,
  threadId,
  setMessages,
  isAuthenticated,
  requestGuardedAction,
}) {
  const toast = useAppToast();
  const [recentThreads, setRecentThreads] = useState([]);
  const [deletingThreadId, setDeletingThreadId] = useState(null);
  // Состояние загрузки сайдбара: раньше провал глотался (silent) и был неотличим
  // от «Нет чатов». Теперь показываем skeleton / ошибку с «Повторить».
  const [isLoadingThreads, setIsLoadingThreads] = useState(false);
  const [threadsError, setThreadsError] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const reloadThreads = useCallback(() => setReloadNonce((n) => n + 1), []);

  // Первичная загрузка списка чатов. Гейт по isAuthenticated: у гостя чатов нет и
  // getUserChats вернёт 401 — не показываем ему ложную ошибку.
  useEffect(() => {
    if (!isAuthenticated) {
      setRecentThreads([]);
      setThreadsError(false);
      setIsLoadingThreads(false);
      return undefined;
    }
    let cancelled = false;
    setIsLoadingThreads(true);
    setThreadsError(false);
    (async () => {
      try {
        const { getUserChats } = await import("@api/chat");
        const data = await getUserChats(null, 15);
        if (cancelled) return;
        const list = Array.isArray(data) ? data : (data.chats || data.threads || []);
        setRecentThreads(list);
      } catch {
        if (!cancelled) setThreadsError(true);
      } finally {
        if (!cancelled) setIsLoadingThreads(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, reloadNonce]);

  const upsertRecentThread = useCallback((targetThreadId, titleCandidate) => {
    const tid = String(targetThreadId || "").trim();
    if (!tid) return;
    const nextTitle = (String(titleCandidate || "").trim() || `Чат ${tid.slice(0, 8)}`).slice(0, 72);

    setRecentThreads((prev) => {
      const normalized = Array.isArray(prev) ? prev : [];
      const existing = normalized.find((thread) => {
        const candidateId = thread?.thread_id || thread?.id || thread;
        return String(candidateId) === tid;
      });
      const nextItem = existing ? { ...existing, title: nextTitle } : { thread_id: tid, title: nextTitle };
      const rest = normalized.filter((thread) => {
        const candidateId = thread?.thread_id || thread?.id || thread;
        return String(candidateId) !== tid;
      });
      return [nextItem, ...rest].slice(0, 18);
    });
  }, []);

  const deleteThread = useCallback(async (targetThreadId) => {
    if (!targetThreadId || deletingThreadId === targetThreadId) return;

    setDeletingThreadId(targetThreadId);
    try {
      const { deleteChatThread } = await import("@api/chat");
      await deleteChatThread(targetThreadId, resolveSessionUserId() || null);

      setRecentThreads((prev) => prev.filter((candidate) => {
        const candidateId = candidate?.thread_id || candidate?.id || candidate;
        return candidateId !== targetThreadId;
      }));

      if (targetThreadId === threadId) {
        setMessages([]);
        navigate("/chat");
      }
    } catch {
      toast({ title: "Не удалось удалить чат", status: "error", duration: 2200 });
    } finally {
      setDeletingThreadId(null);
    }
  }, [deletingThreadId, navigate, resolveSessionUserId, setMessages, threadId, toast]); // toast is stable (useAppToast)

  const handleDeleteThread = useCallback((thread, event) => {
    event.preventDefault();
    event.stopPropagation();
    const targetThreadId = thread?.thread_id || thread?.id || thread;
    if (!targetThreadId || deletingThreadId === targetThreadId) return;
    const action = () => deleteThread(targetThreadId);
    if (targetThreadId === threadId && requestGuardedAction) {
      requestGuardedAction(action, { returnFocus: event.currentTarget });
      return;
    }
    action();
  }, [deleteThread, deletingThreadId, requestGuardedAction, threadId]);

  return {
    recentThreads,
    setRecentThreads,
    deletingThreadId,
    upsertRecentThread,
    handleDeleteThread,
    isLoadingThreads,
    threadsError,
    reloadThreads,
  };
}
