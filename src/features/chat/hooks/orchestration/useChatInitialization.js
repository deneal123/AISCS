import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { createThreadId } from '../../utils/chatThread';
import { readChatUiSettings } from '../../adapters/chatUiSettingsStorage';
import { normalizeChatUiSettings } from '../../schema/chatUiSettingsSchema';

// Сохранённая локально предпочтительная модель ('' = Auto). Читается синхронно
// на маунте — URL-параметр ?model= всё равно имеет приоритет (см. ниже).
const readPersistedPreferredModel = () => {
  const { settings } = readChatUiSettings();
  return normalizeChatUiSettings(settings).preferredModel || '';
};

export function useChatInitialization(routeThreadId) {
  // 🔴 Идентификатор ОБНОВЛЯЕМЫЙ, а не «один на монтирование». Пока он был неизменным,
  // кнопка «новый чат» возвращала пользователя в ТОТ ЖЕ тред: `/chat` редиректит на
  // `/chat/<fallbackThreadId>`, и второй раз подряд это был тот же самый идентификатор.
  const [fallbackThreadId, setFallbackThreadId] = useState(() => createThreadId());
  const [searchParams] = useSearchParams();
  const [selectedModelOverride, setSelectedModelOverride] = useState(
    () => searchParams.get('model') || readPersistedPreferredModel(),
  );

  const params = useMemo(() => ({
    initialMessage: searchParams.get('initial'),
    initialManualModel: searchParams.get('model') || '',
    initialInputType: searchParams.get('input_type') || '',
    initialWebSearch: searchParams.get('web_search') === 'true',
    initialDeepResearch: searchParams.get('deep_research') === 'true',
    initialFileContext: searchParams.get('file_context') || '',
  }), [searchParams]);

  return {
    state: {
      threadId: routeThreadId || fallbackThreadId,
      selectedModelOverride,
      ...params,
    },
    actions: {
      setSelectedModelOverride,
      // Выдать НОВЫЙ идентификатор и вернуть его же: вызывающему нужно немедленно на него
      // перейти, а состояние обновится асинхронно.
      startFreshThread: () => {
        const next = createThreadId();
        setFallbackThreadId(next);
        return next;
      },
    },
  };
}
