import { useEffect, useState } from 'react';

export const TRACE_STALE_AFTER_MS = 60000;

export function formatTraceElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60 ? `${seconds} с` : `${Math.floor(seconds / 60)} мин ${seconds % 60} с`;
}

export function useTraceActivity(session) {
  const [now, setNow] = useState(Date.now);
  const running = session.status === 'running';
  useEffect(() => {
    if (!running) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, [running, session.id]);
  const last = session.events?.[session.events.length - 1];
  const started = Date.parse(session.startedAt || '') || now;
  const progressTime = Date.parse(session.progress?.updatedAt || '') || 0;
  const eventTime = Date.parse(last?.observedAt || last?.timestamp || '') || 0;
  const observed = Math.max(progressTime, eventTime, started);
  return {
    label: progressTime >= eventTime && session.progress?.label
      ? session.progress.label : last?.title || 'Ожидаю запуска обработки',
    elapsed: formatTraceElapsed(now - started),
    stale: running && now - observed >= TRACE_STALE_AFTER_MS,
    silence: formatTraceElapsed(now - observed),
  };
}
