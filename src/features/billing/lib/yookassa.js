// Ленивая загрузка скрипта виджета ЮKassa (один раз на сессию).

const SRC = 'https://yookassa.ru/checkout-widget/v1/checkout-widget.js';
let loadingPromise = null;

export function loadYooKassaScript() {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'));
  if (window.YooMoneyCheckoutWidget) return Promise.resolve();
  if (loadingPromise) return loadingPromise;

  const existing = document.querySelector(`script[src="${SRC}"]`);
  if (existing) existing.remove();

  loadingPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      loadingPromise = null;
      reject(new Error('Не удалось загрузить виджет ЮKassa'));
    };
    document.body.appendChild(script);
  });
  return loadingPromise;
}
