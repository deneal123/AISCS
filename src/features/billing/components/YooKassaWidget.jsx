import { useEffect, useRef } from 'react';
import { Box } from '@chakra-ui/react';
import { loadYooKassaScript } from '../lib/yookassa';

const CONTAINER_ID = 'yookassa-payment-form';

/**
 * Встраиваемый виджет ЮKassa. Получает confirmation_token (создан на бэке) и
 * return_url, рендерит платёжную форму. После успешной оплаты виджет сам
 * редиректит на return_url (/billing/success).
 */
export default function YooKassaWidget({ token, returnUrl, onError }) {
  const widgetRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await loadYooKassaScript();
        if (cancelled || !window.YooMoneyCheckoutWidget) return;
        const widget = new window.YooMoneyCheckoutWidget({
          confirmation_token: token,
          return_url: returnUrl,
          error_callback: (err) => onError?.(err),
        });
        widgetRef.current = widget;
        widget.render(CONTAINER_ID);
      } catch (err) {
        if (!cancelled) onError?.(err);
      }
    })();

    return () => {
      cancelled = true;
      try {
        widgetRef.current?.destroy?.();
      } catch {
        /* noop */
      }
      widgetRef.current = null;
    };
  }, [token, returnUrl, onError]);

  return <Box id={CONTAINER_ID} minH="200px" />;
}
