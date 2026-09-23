import { useCallback, useEffect, useMemo, useState } from "react";

/**
 * Онбординг-прогресс (лёгкая геймификация чата). Отмечает РЕАЛЬНЫЕ действия
 * пользователя (без фейковых данных, по бренд-принципу InCellCorp): первый
 * вопрос, проба веб-поиска, сохранение факта в память. Хранится в localStorage
 * пер-пользователь; карточку можно скрыть.
 */

export const ONBOARDING_STEPS = [
  { id: "first_message", label: "Задайте первый вопрос" },
  { id: "web_search", label: "Попробуйте веб-поиск" },
  { id: "memory", label: "Сохраните факт в память" },
];

const keyFor = (userId) => `gpthub:onboarding:${userId || "guest"}`;

function readState(userId) {
  try {
    const raw = window.localStorage.getItem(keyFor(userId));
    return raw ? JSON.parse(raw) : { done: {}, dismissed: false };
  } catch {
    return { done: {}, dismissed: false };
  }
}

function writeState(userId, state) {
  try {
    window.localStorage.setItem(keyFor(userId), JSON.stringify(state));
  } catch {
    /* no-op */
  }
}

export function useOnboardingProgress(userId) {
  const [state, setState] = useState(() => readState(userId));

  // Перечитать при смене пользователя.
  useEffect(() => {
    setState(readState(userId));
  }, [userId]);

  const markDone = useCallback(
    (id) => {
      setState((prev) => {
        if (prev.done[id]) return prev;
        const next = { ...prev, done: { ...prev.done, [id]: true } };
        writeState(userId, next);
        return next;
      });
    },
    [userId],
  );

  const dismiss = useCallback(() => {
    setState((prev) => {
      const next = { ...prev, dismissed: true };
      writeState(userId, next);
      return next;
    });
  }, [userId]);

  const steps = useMemo(
    () => ONBOARDING_STEPS.map((s) => ({ ...s, done: Boolean(state.done[s.id]) })),
    [state.done],
  );
  const completedCount = steps.filter((s) => s.done).length;
  const allDone = completedCount === steps.length;

  // Результат МЕМОИЗИРОВАН: этот объект уходит пропом в ChatMessagesArea, а новый
  // объект на каждый рендер ломал бы её memo — и лента сообщений пере-сверялась бы
  // целиком на любой перерисовке страницы (открытие дровера, ввод, настройки),
  // из-за чего слайд шторок и списки заметно тормозили.
  return useMemo(
    () => ({
      steps,
      completedCount,
      total: steps.length,
      allDone,
      dismissed: Boolean(state.dismissed),
      markDone,
      dismiss,
    }),
    [steps, completedCount, allDone, state.dismissed, markDone, dismiss],
  );
}
