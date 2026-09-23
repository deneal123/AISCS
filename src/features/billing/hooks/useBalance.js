import { useCallback, useEffect, useState } from 'react';

/**
 * Загружает баланс кредитов. Паттерн как у useProfileData: cancelled-guard +
 * lazy-import API. reload() — для принудительного обновления (после оплаты/чата).
 */
export function useBalance({ enabled = true } = {}) {
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { getBalance } = await import('@api/billing');
      const data = await getBalance();
      setBalance(data);
      return data;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const { getBalance } = await import('@api/billing');
        const data = await getBalance();
        if (!cancelled) setBalance(data);
      } catch (err) {
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { balance, loading, error, reload };
}
