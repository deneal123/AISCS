import { useCallback, useMemo } from 'react';

/**
 * Панель графа знаний: открытие (с гейтом авторизации) и три действия — сводка,
 * поиск, сброс.
 *
 * user_id никуда не передаётся: граф берётся по авторизованному пользователю на
 * бэкенде. Это не мелочь — граф личный, и подставлять чужой id из URL быть не должно.
 */
export function useGraphPanel({ isAuthenticated, graphDisclosure, showAuthModal, sideEffects }) {
  const open = useCallback(() => {
    if (!isAuthenticated) {
      showAuthModal(
        'Граф знаний доступен после входа',
        'Войдите в аккаунт, чтобы увидеть связи в своих документах.',
        'graph_requires_auth'
      );
      return;
    }
    graphDisclosure.onOpen();
  }, [isAuthenticated, graphDisclosure, showAuthModal]);

  const loadSummary = useCallback(async () => {
    try {
      const { getGraphSummary } = await import('@api/chat');
      return await getGraphSummary();
    } catch {
      // Сводка недоступна — это не повод шуметь тостом: панель сама покажет пустое
      // состояние. Шумим только на действиях, которые пользователь запросил явно.
      return { enabled: true, exists: false };
    }
  }, []);

  const search = useCallback(
    async (query) => {
      try {
        const { searchGraph } = await import('@api/chat');
        const data = await searchGraph(query);
        // Ровно то же, что видит модель: дословные фрагменты (эмбеддинги) и связи (граф).
        return { passages: data?.passages || [], relations: data?.context || '' };
      } catch {
        sideEffects.notify({
          title: 'Поиск по базе знаний не удался',
          status: 'warning',
          duration: 2500,
        });
        return { passages: [], relations: '' };
      }
    },
    [sideEffects]
  );

  const openHtml = useCallback(async () => {
    try {
      const { getGraphHtml } = await import('@api/chat');
      const html = await getGraphHtml();
      // Blob, а не прямая ссылка: HTML приходит авторизованным запросом (граф личный),
      // и отдать его браузеру можно только уже полученным.
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
      window.open(url, '_blank', 'noopener,noreferrer');
      // Освобождаем после того, как вкладка успела забрать содержимое.
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      sideEffects.notify({
        title: 'Граф ещё не построен',
        description: 'Загрузите документ или архив с кодом — граф появится автоматически.',
        status: 'info',
        duration: 3000,
      });
    }
  }, [sideEffects]);

  const remove = useCallback(async () => {
    try {
      const { deleteGraph } = await import('@api/chat');
      await deleteGraph();
      sideEffects.notify({ title: 'Граф знаний очищен', status: 'success', duration: 2000 });
    } catch {
      sideEffects.notify({
        title: 'Не удалось очистить граф',
        status: 'warning',
        duration: 2500,
      });
    }
  }, [sideEffects]);

  return useMemo(
    () => ({
      openGraphPanel: open,
      loadGraphSummary: loadSummary,
      searchGraphHandler: search,
      deleteGraphHandler: remove,
      openGraphHtmlHandler: openHtml,
    }),
    [open, loadSummary, search, remove, openHtml]
  );
}
