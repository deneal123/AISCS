import { useEffect, useState } from 'react';
import { getChatProviderStatus } from '@shared/api/chat';

/** Один пассивный читатель: в шапке на десктопе, в композере на мобильном. */
export function useProviderStatus() {
  const [status, setStatus] = useState({ data: null, stale: false });
  useEffect(() => {
    let retired = false;
    let controller;
    let interval;
    let deadline;
    let pending = false;
    const refresh = async () => {
      if (retired || pending || document.visibilityState === 'hidden') return;
      pending = true;
      controller = new AbortController();
      deadline = setTimeout(() => controller.abort(), 4000);
      try {
        const data = await getChatProviderStatus({ signal: controller.signal });
        if (!retired) setStatus((previous) => {
          // A bounded unknown response can mean the backend lost its sidecar.
          // Retain prior evidence, but never continue presenting it as fresh.
          if (data?.state === 'unknown' && data.providers?.length === 0
            && previous.data?.providers?.length) return { ...previous, stale: true };
          return { data, stale: false };
        });
      } catch {
        if (!retired) setStatus((previous) => ({ ...previous, stale: true }));
      } finally {
        clearTimeout(deadline);
        pending = false;
      }
    };
    const resume = () => {
      if (document.visibilityState !== 'hidden') {
        setStatus((previous) => ({ ...previous, stale: !!previous.data }));
        refresh();
      }
    };
    refresh();
    interval = setInterval(refresh, 30000);
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('online', resume);
    return () => {
      retired = true;
      controller?.abort();
      clearInterval(interval);
      clearTimeout(deadline);
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('online', resume);
    };
  }, []);
  return status;
}
