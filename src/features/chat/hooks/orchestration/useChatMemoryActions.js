import { useCallback } from 'react';

/**
 * Owns mutations and queries for the memory drawer.
 *
 * The page container coordinates surfaces; this hook keeps the provider-
 * agnostic memory workflow, profile counter and user feedback transactional
 * from the UI's point of view.
 */
export function useChatMemoryActions({
  resolveSessionUserId,
  setMemoryFacts,
  setMemoryDashboard,
  setProfileMemoryCount,
  notify,
}) {
  const searchMemoryFacts = useCallback(async (query) => {
    const userId = resolveSessionUserId();
    if (!userId) return;
    try {
      const { getUserMemory, searchMemory } = await import('@api/chat');
      const normalized = String(query || '').trim();
      const data = normalized
        ? await searchMemory(userId, normalized)
        : await getUserMemory(userId);
      setMemoryFacts(Array.isArray(data?.facts) ? data.facts : []);
    } catch {
      notify({ title: 'Поиск по памяти не удался', status: 'warning', duration: 2500 });
    }
  }, [notify, resolveSessionUserId, setMemoryFacts]);

  const addMemoryFact = useCallback(async (value) => {
    const text = typeof value === 'string' ? value.trim() : '';
    const userId = resolveSessionUserId();
    if (!text || !userId) return;
    try {
      const { addMemoryFact: persistFact, getUserMemory } = await import('@api/chat');
      const key = text.toLowerCase().replace(/\s+/g, '_').slice(0, 40) || 'note';
      await persistFact(userId, 'note', key, text);
      const data = await getUserMemory(userId);
      const facts = Array.isArray(data?.facts) ? data.facts : [];
      setMemoryFacts(facts);
      setProfileMemoryCount(facts.length);
    } catch {
      notify({ title: 'Не удалось добавить факт', status: 'warning', duration: 2500 });
    }
  }, [notify, resolveSessionUserId, setMemoryFacts, setProfileMemoryCount]);

  const deleteMemoryFact = useCallback(async (factId) => {
    const userId = resolveSessionUserId();
    if (!userId) return;
    try {
      const { deleteMemoryFact: removeFact } = await import('@api/chat');
      await removeFact(userId, factId);
      setMemoryFacts((previous) => {
        const next = previous.filter((fact) => fact.id !== factId);
        setProfileMemoryCount(next.length);
        return next;
      });
    } catch {
      notify({ title: 'Не удалось удалить факт', status: 'warning', duration: 2500 });
    }
  }, [notify, resolveSessionUserId, setMemoryFacts, setProfileMemoryCount]);

  const clearAllMemory = useCallback(async () => {
    const userId = resolveSessionUserId();
    if (!userId) return;
    try {
      const { clearUserMemory } = await import('@api/chat');
      const report = await clearUserMemory(userId);
      setMemoryFacts([]);
      setMemoryDashboard(null);
      setProfileMemoryCount(0);
      const semanticMemoryCleared = report?.memos?.ok !== false;
      notify({
        title: 'Память очищена',
        description: semanticMemoryCleared
          ? undefined
          : 'Факты удалены, но семантическую память очистить не удалось. Попробуйте позже.',
        status: semanticMemoryCleared ? 'success' : 'warning',
        duration: semanticMemoryCleared ? 2000 : 4000,
      });
    } catch {
      notify({ title: 'Не удалось очистить память', status: 'warning', duration: 2500 });
    }
  }, [
    notify,
    resolveSessionUserId,
    setMemoryDashboard,
    setMemoryFacts,
    setProfileMemoryCount,
  ]);

  return {
    searchMemoryFacts,
    addMemoryFact,
    deleteMemoryFact,
    clearAllMemory,
  };
}
