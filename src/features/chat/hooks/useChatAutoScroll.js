import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { prefersReducedMotion } from '@utils/motion';

/**
 * Авто-прокрутка ленты чата — единый источник правды (заменил instant-эффект
 * контейнера и локальное состояние скролла в ленте).
 *
 * Прилипает ко дну во время стрима, но ПРЕРЫВАЕТСЯ жестом пользователя и сам
 * возобновляется через RESUME_AFTER_IDLE_MS бездействия. До-пинивается при
 * асинхронном росте высоты (ленивые кодоблоки, картинки) и уважает
 * prefers-reduced-motion.
 *
 * @param {React.RefObject<HTMLElement>} params.scrollRef контейнер прокрутки
 * @param {string} params.contentSignal дешёвый сигнал контента
 * @param {boolean} params.isStreaming идёт ли стрим ответа
 */

// Единый порог «прилипания» ко дну (px): в этой зоне лента следует за стримом.
const STICK_THRESHOLD = 110;
// Сколько мс без жеста пользователя ждать, прежде чем возобновить авто-скролл.
const RESUME_AFTER_IDLE_MS = 2500;

export function useChatAutoScroll({ scrollRef, contentSignal, isStreaming }) {
  // Намерение пользователя «держаться дна». По умолчанию — да
  // (свежий тред открывается у нижней кромки).
  const stickRef = useRef(true);
  // true, пока в полёте НАШ программный (smooth) скролл — чтобы его промежуточные
  // позиции не прочитались в onScroll как «пользователь ушёл вверх» и не сорвали follow.
  const programmaticRef = useRef(false);
  // Пользователь активно скроллит жестом (колесо/тач) — пауза авто-скролла, чтобы
  // пин НЕ возвращал его ко дну на каждом токене (иначе жест «не удержать»).
  const userPausedRef = useRef(false);
  const guardTimerRef = useRef(0);
  const idleTimerRef = useRef(0);
  const rafRef = useRef(0);
  // Актуальное isStreaming для слушателей (замыкание не устаревает).
  const isStreamingRef = useRef(isStreaming);
  isStreamingRef.current = isStreaming;
  // Состояние нужно ТОЛЬКО кнопке «вниз»; сет дёргаем лишь на флипе значения.
  const [atBottom, setAtBottom] = useState(true);

  const setAtBottomIfChanged = useCallback((next) => {
    setAtBottom((prev) => (prev === next ? prev : next));
  }, []);

  const clearGuard = useCallback(() => {
    window.clearTimeout(guardTimerRef.current);
    guardTimerRef.current = 0;
    programmaticRef.current = false;
  }, []);

  // Мгновенный пин ко дну (per-token / async-рост). Крошечные дельты читаются
  // плавно; CSS-smooth на КАЖДЫЙ токен, наоборот, «дёргался» бы.
  const pinInstant = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [scrollRef]);

  // Один пин на кадр: коалесцируем шквал токенов/ресайзов в единственный rAF.
  // Пин не выполняется, пока пользователь держит паузу жестом.
  const schedulePin = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = 0;
      if (stickRef.current && !userPausedRef.current) pinInstant();
    });
  }, [pinInstant]);

  // Возобновить следование ко дну (после простоя жеста / возврата ко дну / кнопки).
  const resumeFollow = useCallback(() => {
    window.clearTimeout(idleTimerRef.current);
    idleTimerRef.current = 0;
    userPausedRef.current = false;
    stickRef.current = true;
    setAtBottomIfChanged(true);
    const el = scrollRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (dist <= 2) return;
    const behavior = prefersReducedMotion() ? 'auto' : 'smooth';
    if (behavior === 'smooth') {
      programmaticRef.current = true;
      window.clearTimeout(guardTimerRef.current);
      guardTimerRef.current = window.setTimeout(clearGuard, 500);
    }
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, [scrollRef, setAtBottomIfChanged, clearGuard]);

  // Жест пользователя (колесо/тач): ставим авто-скролл на паузу и заводим таймер
  // возобновления. Только во время стрима — вне стрима прерывать нечего.
  const onUserGesture = useCallback(() => {
    if (!isStreamingRef.current) return;
    userPausedRef.current = true;
    stickRef.current = false;
    window.clearTimeout(idleTimerRef.current);
    idleTimerRef.current = window.setTimeout(resumeFollow, RESUME_AFTER_IDLE_MS);
  }, [resumeFollow]);

  // Подписка на wheel/touchmove контейнера (passive) — распознаём именно ЖЕСТ,
  // в отличие от onScroll, который срабатывает и на наш программный пин.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    el.addEventListener('wheel', onUserGesture, { passive: true });
    el.addEventListener('touchmove', onUserGesture, { passive: true });
    return () => {
      el.removeEventListener('wheel', onUserGesture);
      el.removeEventListener('touchmove', onUserGesture);
    };
  }, [scrollRef, onUserGesture]);

  // Дискретный ПЛАВНЫЙ возврат ко дну (кнопка «вниз»). Снимает паузу жеста.
  const scrollToBottom = useCallback(() => {
    window.clearTimeout(idleTimerRef.current);
    idleTimerRef.current = 0;
    userPausedRef.current = false;
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = true;
    setAtBottomIfChanged(true);
    const behavior = prefersReducedMotion() ? 'auto' : 'smooth';
    if (behavior === 'smooth') {
      programmaticRef.current = true;
      window.clearTimeout(guardTimerRef.current);
      guardTimerRef.current = window.setTimeout(clearGuard, 500);
    }
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, [scrollRef, setAtBottomIfChanged, clearGuard]);

  // onScroll: моделируем намерение пользователя. Пока идёт НАШ smooth-скролл
  // (programmaticRef), промежуточные позиции глотаем; как дошли до дна — снимаем guard.
  const handleScroll = useCallback((e) => {
    const el = e.currentTarget;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (programmaticRef.current) {
      if (dist <= 2) {
        clearGuard();
        stickRef.current = true;
        userPausedRef.current = false;
        setAtBottomIfChanged(true);
      }
      return;
    }
    // Пользователь на паузе (скроллит сам): не трогаем stick, обновляем только
    // кнопку; вернулся вплотную ко дну — сразу возобновляем следование.
    if (userPausedRef.current) {
      if (dist <= 2) resumeFollow();
      else setAtBottomIfChanged(dist < STICK_THRESHOLD);
      return;
    }
    const next = dist < STICK_THRESHOLD;
    stickRef.current = next;
    setAtBottomIfChanged(next);
  }, [clearGuard, setAtBottomIfChanged, resumeFollow]);

  // Follow при росте контента (per-token). Ключ — ДЕШЁВЫЙ contentSignal
  // ("count:lastType:lastLen"), а не весь массив messages.
  const prevSignalRef = useRef(contentSignal);
  useLayoutEffect(() => {
    const parse = (sig) => {
      const parts = String(sig ?? '').split(':');
      return { count: Number(parts[0]) || 0, type: parts[1] || '' };
    };
    const cur = parse(contentSignal);
    const prev = parse(prevSignalRef.current);
    prevSignalRef.current = contentSignal;

    // Форс-пин на отправку: появилось НОВОЕ сообщение и оно от пользователя —
    // раскрываем его ход, даже если он до этого читал выше (снимаем паузу жеста).
    if (cur.count > prev.count && cur.type === 'user') {
      window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = 0;
      userPausedRef.current = false;
      stickRef.current = true;
      setAtBottomIfChanged(true);
    }

    if (stickRef.current && !userPausedRef.current) {
      // СИНХРОННО в layout-эффекте (до отрисовки): контент только что вырос —
      // приклеиваем скролл к низу В ТОМ ЖЕ кадре. rAF-пин отставал на 1 кадр и
      // контент успевал «дёрнуться» вниз перед доскроллом. ResizeObserver
      // (асинхронный рост высоты) по-прежнему использует schedulePin.
      pinInstant();
      // На финише стрима (isStreaming=false) контент «усаживается» (маркдаун,
      // трейлинг-пробелы) — гарантируем корректный флаг кнопки: мы у дна.
      if (!isStreaming) setAtBottomIfChanged(true);
    }
  }, [contentSignal, isStreaming, pinInstant, setAtBottomIfChanged]);

  // Стрим закончился — сбрасываем паузу/таймер, возвращаемся к обычному режиму.
  useEffect(() => {
    if (!isStreaming) {
      window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = 0;
      userPausedRef.current = false;
    }
  }, [isStreaming]);

  // ResizeObserver на ВНУТРЕННЕМ контент-контейнере: ловит АСИНХРОННЫЙ рост высоты
  // (ленивые кодоблоки, поздний декод картинок) — лечит latch-баг «догоняй сам».
  // Пиним только если «прилипли» и нет паузы жеста; читаем scrollHeight / пишем
  // scrollTop только тут; коалесцируем через общий rAF.
  const observerRef = useRef(null);
  const registerContentRef = useCallback((node) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }
    if (!node || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (stickRef.current && !userPausedRef.current) schedulePin();
    });
    ro.observe(node);
    observerRef.current = ro;
  }, [schedulePin]);

  // Уборка: rAF / таймеры / observer на размонтаже.
  useEffect(() => () => {
    if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
    window.clearTimeout(guardTimerRef.current);
    window.clearTimeout(idleTimerRef.current);
    if (observerRef.current) observerRef.current.disconnect();
  }, []);

  return { handleScroll, atBottom, scrollToBottom, registerContentRef };
}

export default useChatAutoScroll;
