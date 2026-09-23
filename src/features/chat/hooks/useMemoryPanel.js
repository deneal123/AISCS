import { useCallback } from 'react';

/**
 * Открытие панели памяти: проверка авторизации, резолв user_id и загрузка
 * фактов долговременной памяти пользователя.
 */
export function useMemoryPanel({
  isAuthenticated,
  memoryDisclosure,
  resolveSessionUserId,
  setMemoryFacts,
  setMemoryDashboard,
  setProfileMemoryCount,
  showAuthModal,
  sideEffects,
}) {
  return useCallback(async () => {
    if (!isAuthenticated) {
      showAuthModal(
        'Память доступна после входа',
        'Войдите в аккаунт, чтобы увидеть и управлять долговременной памятью.',
        'memory_requires_auth'
      );
      return;
    }
    memoryDisclosure.onOpen();
    try {
      const { getUserMemory, getUserMemoryDashboard } = await import('@api/chat');
      let effectiveUserId = resolveSessionUserId();
      if (!effectiveUserId) {
        const { fetchProfile } = await import('@api/profile');
        const profile = await fetchProfile();
        effectiveUserId = profile?.id ? String(profile.id) : '';
        if (effectiveUserId && typeof window !== 'undefined') {
          window.sessionStorage.setItem('user_id', effectiveUserId);
        }
      }
      if (!effectiveUserId) {
        throw new Error('user_id is missing in session');
      }
      // Оба запроса стартуют СРАЗУ. Раньше дашборд уходил только после ответа по
      // фактам, и его задержка складывалась с их задержкой — блок семантической памяти
      // появлялся заметно позже остальной панели. Ходят они в разные хранилища
      // (Postgres и MemOS), ждать друг друга им незачем.
      //
      // ⚠️ `.catch` вешаем ПРИ СОЗДАНИИ промиса, а не на месте `await`: до него ещё
      // ждать ответа по фактам, и упавший раньше дашборд дал бы unhandled rejection.
      const factsRequest = getUserMemory(effectiveUserId);
      const dashboardRequest = setMemoryDashboard
        ? getUserMemoryDashboard(effectiveUserId).catch(() => null)
        : null;

      // Факты рисуем, не дожидаясь дашборда: он вспомогательный, и его сбой или
      // медлительность не должны задерживать основную часть панели.
      const data = await factsRequest;
      const facts = data.facts || [];
      setMemoryFacts(facts);
      setProfileMemoryCount(Array.isArray(facts) ? facts.length : 0);

      if (dashboardRequest) {
        const dash = await dashboardRequest;
        setMemoryDashboard(dash && typeof dash === 'object' && Object.keys(dash).length ? dash : null);
      }
    } catch {
      sideEffects.notify({
        title: 'Не удалось загрузить факты памяти',
        description: 'Проверьте, что сессия активна, и повторите попытку.',
        status: 'warning',
        duration: 2500,
      });
    }
  }, [isAuthenticated, memoryDisclosure, resolveSessionUserId, setMemoryFacts, setMemoryDashboard, setProfileMemoryCount, showAuthModal, sideEffects]);
}
