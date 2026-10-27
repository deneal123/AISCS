import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const EMPTY_CONTEXT = {
  tokens: 0,
  windowTokens: 0,
  modelWindow: 0,
  bySection: {},
  pct: 0,
  threshold: 85,
  hasWindow: false,
};

/** Owns context-window reporting and manual/automatic compaction lifecycle. */
export function useChatContextCompaction({ messages, isLoading, notify, sendControlRef }) {
  const [compacting, setCompacting] = useState(false);
  const [compactedAfterId, setCompactedAfterId] = useState(null);
  const [compactedSummary, setCompactedSummary] = useState('');
  const [compactedOverride, setCompactedOverride] = useState(false);
  const lastMessageIdRef = useRef(null);
  const compactedAtMessageRef = useRef(null);
  const autoCompactedRef = useRef(false);
  const busyTimerRef = useRef(null);
  const compactingRef = useRef(false);
  const notifyCompaction = useCallback((options) => notify({
    ...options, operationId: 'context-compaction',
  }), [notify]);

  useEffect(() => () => window.clearTimeout(busyTimerRef.current), []);

  const onCompacted = useCallback((event, ok) => {
    compactingRef.current = false;
    setCompacting(false);
    window.clearTimeout(busyTimerRef.current);
    if (ok) {
      setCompactedAfterId(lastMessageIdRef.current);
      compactedAtMessageRef.current = lastMessageIdRef.current;
      setCompactedOverride(true);
      setCompactedSummary(String(event?.summary || ''));
      notifyCompaction({
        title: 'Контекст сжат',
        description: 'Диалог свёрнут в резюме — над последним сообщением появился разделитель.',
        status: 'success',
        duration: 3000,
      });
      return;
    }
    const empty = event?.reason === 'empty';
    notifyCompaction({
      title: empty ? 'Сжимать нечего' : 'Контекст не сжат',
      description: empty
        ? 'Нет истории для сжатия.'
        : 'Не удалось подготовить резюме. Текущая история сохранена.',
      status: empty ? 'info' : 'warning',
      duration: 2500,
    });
  }, [notifyCompaction]);

  const contextInfo = useMemo(() => {
    const list = messages || [];
    lastMessageIdRef.current = list.length ? list[list.length - 1]?.id ?? null : null;
    const report = [...list].reverse().find((message) => (
      message?.metadata?.context
    ))?.metadata?.context;
    if (!(report?.usable > 0)) return EMPTY_CONTEXT;

    const usable = Number(report.usable) || 0;
    const overrideActive = compactedOverride
      && lastMessageIdRef.current === compactedAtMessageRef.current;
    const compactedHistory = overrideActive ? Number(report.by_section?.history) || 0 : 0;
    const used = Math.max(0, (Number(report.used) || 0) - compactedHistory);
    return {
      tokens: used,
      windowTokens: usable,
      modelWindow: Number(report.window) || 0,
      bySection: report.by_section || {},
      pct: Math.min(100, (used / usable) * 100),
      threshold: Number(report.threshold_pct) || 85,
      hasWindow: true,
      compacted: overrideActive,
    };
  }, [compactedOverride, messages]);

  useEffect(() => {
    if (!compactedOverride) return;
    const lastId = messages.length ? messages[messages.length - 1]?.id : null;
    if (lastId && lastId !== compactedAtMessageRef.current) setCompactedOverride(false);
  }, [compactedOverride, messages]);

  const compact = useCallback(() => {
    if (compactingRef.current || isLoading) return;
    compactingRef.current = true;
    if (sendControlRef.current?.('compact_context')) {
      setCompacting(true);
      notifyCompaction({
        title: 'Сжимаю контекст…',
        description: 'Подготавливаю резюме диалога.',
        status: 'info',
        duration: 20000,
      });
      window.clearTimeout(busyTimerRef.current);
      busyTimerRef.current = window.setTimeout(() => {
        compactingRef.current = false;
        setCompacting(false);
        notifyCompaction({
          title: 'Результат сжатия пока неизвестен',
          description: 'Сервер не подтвердил завершение. Текущая история сохранена.',
          status: 'warning',
          duration: 5000,
        });
      }, 15000);
    } else {
      compactingRef.current = false;
      notifyCompaction({
        title: 'Сжатие не запущено',
        description: 'Нет соединения с сервером. Дождитесь восстановления связи.',
        status: 'warning',
        duration: 3500,
      });
    }
  }, [isLoading, notifyCompaction, sendControlRef]);

  useEffect(() => {
    if (!contextInfo.hasWindow || isLoading) return;
    const { pct, threshold } = contextInfo;
    if (pct >= threshold && !compacting && !autoCompactedRef.current) {
      autoCompactedRef.current = true;
      compact();
    } else if (pct < threshold - 25) {
      autoCompactedRef.current = false;
    }
  }, [compact, compacting, contextInfo, isLoading]);

  return {
    compacting,
    compactedAfterId,
    compactedSummary,
    contextInfo,
    compact,
    onCompacted,
  };
}
