import { useEffect } from "react";
import { useLocation } from "react-router-dom";

// Сколько кадров ждём появления секции: при переходе с другой страницы роутер
// монтирует лендинг не мгновенно, и в момент навигации якоря в DOM ещё нет.
const MAX_FRAMES = 40;

/**
 * Прокрутка при смене маршрута.
 *
 * Без хеша — в начало страницы (иначе после навигации пользователь оказывается
 * посреди новой страницы).
 *
 * С хешем (`/#how` из футера) — к соответствующей секции. Раньше этот случай не
 * обрабатывался: браузер не мог найти якорь, потому что SPA ещё не отрисовала
 * лендинг, а этот компонент тут же уводил скролл наверх — ссылки футера
 * «Как работает» / «Почему мы» / «Возможности» с любой НЕ-лендинговой страницы
 * вели просто на верх главной.
 */
function ScrollToTop() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (!hash) {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
      return undefined;
    }

    const id = decodeURIComponent(hash.slice(1));
    let frame = 0;
    let raf = 0;
    const seek = () => {
      const el = document.getElementById(id);
      if (el) {
        // scroll-margin-top секций (motion.css) уводит их из-под sticky-шапки.
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (frame++ < MAX_FRAMES) raf = requestAnimationFrame(seek);
    };
    raf = requestAnimationFrame(seek);
    return () => cancelAnimationFrame(raf);
  }, [pathname, hash]);

  return null;
}

export default ScrollToTop;
