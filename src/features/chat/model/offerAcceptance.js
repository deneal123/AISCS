/**
 * Как принимается предложение: режимом или инструментом.
 *
 * 🔴 ПРЕДЛОЖЕНИЯ БЫВАЮТ ДВУХ РОДОВ, И ПРИНИМАЮТСЯ ОНИ ПО-РАЗНОМУ. Режим перезапускает
 * прогон другим маршрутом (`routeOverride`); инструмент маршрут не меняет — он лишь
 * снимает запор с признака контекста. Отправив имя инструмента как маршрут, клиент послал
 * бы значение, которого среди маршрутов нет: бэкенд отверг бы запрос схемой, а человек
 * увидел бы, что кнопка не работает, без единого объяснения.
 *
 * ⚠️ Вынесено из контейнера ОТДЕЛЬНО, потому что это решение, а не разметка: в контейнере
 * его нечем проверить, и мутация «слать всё маршрутом» оставалась зелёной.
 */

/** Инструменты, у которых есть свой признак согласия. Ключ — имя из предложения. */
const TOOL_CONSENT = {
  watch_video: 'watchVideo',
  expensive_run: 'confirmExpensiveRun',
};

/**
 * Опции отправки для принятого предложения.
 *
 * @param {string} mode  имя режима или инструмента из карточки
 * @param {string} [kind] род предложения: 'tool' — инструмент, иначе режим
 * @returns {object} опции для отправителя сообщения
 */
export function offerSendOptions(offerOrMode, kind) {
  const offer = offerOrMode && typeof offerOrMode === 'object' ? offerOrMode : null;
  const name = String(offer?.mode || offerOrMode || '');
  const offerKind = offer?.offer_kind || kind;
  if (name === 'expensive_run' && offer?.offer_id) {
    return {
      confirmOfferId: String(offer.offer_id),
      skipUserAppend: true,
    };
  }
  if (offerKind !== 'tool') return { routeOverride: name };
  const flag = TOOL_CONSENT[name];
  // ⚠️ Незнакомый инструмент — ПУСТЫЕ опции, а не «отправим маршрутом на всякий случай»:
  // запрос с несуществующим маршрутом отвергнет схема, и кнопка молча перестанет работать.
  // Пустые опции означают «отправить как обычное сообщение» — ответ будет, просто без
  // дорогой способности.
  return flag ? { [flag]: true } : {};
}

export default offerSendOptions;
