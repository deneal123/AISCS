import { createContext, useContext, useEffect, useMemo, useRef } from 'react';
import { useAuth } from '@app/providers';
import { useBalance } from '../hooks/useBalance';
import { useUserEvents } from '../hooks/useUserEvents';

const BillingContext = createContext({ balance: null, loading: false, reload: () => {} });

// Возврат на вкладку не должен дёргать сервер чаще, чем раз в полминуты: баланс
// так быстро не меняется, а Alt-Tab туда-сюда давал по запросу на каждое
// переключение. Явный сигнал `billing:refresh` (после ответа модели) не троттлим —
// там баланс точно изменился.
const FOCUS_REFRESH_INTERVAL_MS = 30_000;

/**
 * Общий баланс кредитов для всего приложения (Header/composer/drawer/page) —
 * один источник, без дублирующих запросов. Обновляется по событию
 * `billing:refresh` (диспатчится после завершения ответа модели) и при возврате
 * фокуса на вкладку.
 */
export function BillingProvider({ children }) {
  const { isAuthenticated } = useAuth();
  const { balance, loading, reload } = useBalance({ enabled: isAuthenticated });
  const lastFocusReloadRef = useRef(0);

  // Персональный WS-канал: пополнение админом происходит вне сессии пользователя, и ни
  // ответ модели, ни фокус вкладки его не триггерят. Событие `balance_refresh` из этого
  // канала — единственное, что доставляет такой сигнал на любую открытую страницу.
  useUserEvents({ enabled: isAuthenticated, onBalanceRefresh: reload });

  useEffect(() => {
    if (!isAuthenticated) return undefined;

    const onRefresh = () => reload();
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const now = Date.now();
      if (now - lastFocusReloadRef.current < FOCUS_REFRESH_INTERVAL_MS) return;
      lastFocusReloadRef.current = now;
      reload();
    };

    window.addEventListener('billing:refresh', onRefresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.removeEventListener('billing:refresh', onRefresh);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [isAuthenticated, reload]);

  // Мемоизация значения: иначе новый объект каждый рендер провайдера ре-рендерит
  // всех потребителей (Header/composer/drawer/page).
  const value = useMemo(() => ({ balance, loading, reload }), [balance, loading, reload]);

  return (
    <BillingContext.Provider value={value}>
      {children}
    </BillingContext.Provider>
  );
}

export const useBillingContext = () => useContext(BillingContext);

/** Сигнал «баланс мог измениться» — обновить везде, где показан. */
export const notifyBillingRefresh = () => {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('billing:refresh'));
  }
};
