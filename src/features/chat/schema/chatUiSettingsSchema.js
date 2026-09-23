import { defaultChatUiSettings } from '../constants/chatUiSettings';

const toBoolean = (value, fallback) => (typeof value === 'boolean' ? value : fallback);
const toStringValue = (value, fallback) => (typeof value === 'string' ? value : fallback);

export const normalizeChatUiSettings = (raw) => {
  const source = raw && typeof raw === 'object' ? raw : {};
  return {
    showTracePanel: toBoolean(source.showTracePanel, defaultChatUiSettings.showTracePanel),
    // Сохранённые `webSearchEnabled`/`deepResearchEnabled` НАМЕРЕННО отбрасываются:
    // флаги выводятся из режима, а старое `true` из localStorage иначе включало бы
    // поиск на каждом сообщении без единого элемента управления.
    multiIntentEnabled: toBoolean(source.multiIntentEnabled, defaultChatUiSettings.multiIntentEnabled),
    planningEnabled: toBoolean(source.planningEnabled, defaultChatUiSettings.planningEnabled),
    // Только строки и не больше потолка: в localStorage могло остаться что угодно,
    // а мусор здесь уехал бы прямо в тело запроса.
    personaIds: Array.isArray(source.personaIds)
      ? source.personaIds.filter((x) => typeof x === 'string' && x).slice(0, 2)
      : defaultChatUiSettings.personaIds,
    memoryEnabled: toBoolean(source.memoryEnabled, defaultChatUiSettings.memoryEnabled),
    preferredModel: toStringValue(source.preferredModel, defaultChatUiSettings.preferredModel),
    ldrModel: toStringValue(source.ldrModel, defaultChatUiSettings.ldrModel),
    ldrStrategy: toStringValue(source.ldrStrategy, defaultChatUiSettings.ldrStrategy),
    transcriptionMode: toStringValue(source.transcriptionMode, defaultChatUiSettings.transcriptionMode),
    transcriptionModel: toStringValue(source.transcriptionModel, defaultChatUiSettings.transcriptionModel),
  };
};
