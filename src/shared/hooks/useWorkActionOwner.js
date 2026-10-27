import { useCallback, useEffect, useRef, useState } from 'react';

// Mutations cannot be undone by aborting their response. Keep their UI ownership
// separate: stale work may finish on the server, but cannot affect another chat.
export function useWorkActionOwner({ threadId, active }) {
  const [busy, setBusy] = useState('');
  const mounted = useRef(false);
  const currentThread = useRef(threadId);
  const enabled = useRef(active);
  const operation = useRef(null);
  currentThread.current = threadId;
  enabled.current = active;

  useEffect(() => {
    mounted.current = true;
    operation.current = null;
    setBusy('');
    return () => {
      mounted.current = false;
      operation.current = null;
    };
  }, [threadId]);

  const begin = useCallback((expectedThread, label) => {
    if (!mounted.current || !enabled.current || !expectedThread
      || currentThread.current !== expectedThread || operation.current) return null;
    const ticket = { threadId: expectedThread };
    operation.current = ticket;
    setBusy(label);
    return ticket;
  }, []);

  const owns = useCallback((ticket) => Boolean(ticket) && mounted.current
    && operation.current === ticket && currentThread.current === ticket.threadId, []);
  const isCurrent = useCallback(expected => Boolean(expected) && mounted.current
    && enabled.current && currentThread.current === expected, []);

  const finish = useCallback((ticket) => {
    if (!owns(ticket)) return;
    operation.current = null;
    setBusy('');
  }, [owns]);

  return { busy: operation.current?.threadId === threadId ? busy : '', begin, owns, finish, isCurrent };
}
