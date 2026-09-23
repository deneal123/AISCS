/**
 * Предложение дорогого режима живёт В ТРЕЙСЕ, и ровно в одном месте.
 *
 * 🔴 Под готовым ответом карточка висела ВЕЧНО: человек либо жал кнопку задним числом —
 * через час, когда ответ уже прочитан и не нужен, — либо она просто мозолила глаза.
 * Решение о тысячах кредитов имеет смысл ПО ХОДУ работы, поэтому предложение переехало
 * в панель хода работы и получило серверный отсчёт.
 *
 * ⚠️ ИМЕННО ПЕРЕЕХАЛО, А НЕ ПРОДУБЛИРОВАЛОСЬ: две карточки об одном решении означали бы
 * два разных срока жизни у одного предложения.
 *
 * ⚠️ Проверяем ИСХОДНИК, а не отрендеренный DOM: рендер этих компонентов тянет провайдера
 * темы, стор и десяток моков, и страж превратился бы в тест окружения.
 */
import fs from 'fs';
import path from 'path';

const read = (rel) => fs.readFileSync(path.join(__dirname, '../..', rel), 'utf8');

const MESSAGE_ITEM = read('src/features/chat/components/ChatMessageItem.jsx');
const TRACE_ROW = read('src/features/chat/components/trace/TraceEventRow.jsx');
const LIFECYCLE = read('src/features/chat/hooks/orchestration/useChatStreamingLifecycle.js');
const MESSAGES_AREA = read('src/features/chat/components/ChatMessagesArea.jsx');
const MODE_OFFER = read('src/features/chat/components/ModeOffer.jsx');

describe('размещение предложения режима', () => {
  it('🔴 сообщение больше НЕ рисует карточку предложения', () => {
    expect(MESSAGE_ITEM).not.toMatch(/<ModeOffer/);
    expect(MESSAGE_ITEM).not.toMatch(/from '\.\/ModeOffer'/);
  });

  it('строка трейса рисует её и умеет запускать режим', () => {
    expect(TRACE_ROW).toMatch(/<ModeOffer/);
    expect(TRACE_ROW).toMatch(/onRun=\{onRunMode\}/);
  });

  it('событие оркестратора доезжает до трейса шагом-предложением', () => {
    expect(LIFECYCLE).toContain("event.metadata?.kind === 'mode_offer'");
    expect(LIFECYCLE).toMatch(/kind: 'offer'/);
  });

  it('берёт текст повторного запуска только из user-message anchor, не из trace metadata', () => {
    expect(MODE_OFFER).not.toMatch(/offer\.prompt/);
    expect(MESSAGES_AREA).toContain('onRunMode={onRunMode');
    expect(MESSAGES_AREA).toContain('(offer) => onRunMode(');
    expect(MESSAGES_AREA).toContain('message.content');
    expect(MESSAGES_AREA).toContain('message.id');
  });

  it('чипы источников не привязаны к отправителю', () => {
    const at = MESSAGE_ITEM.indexOf('<MessageSources');
    const condition = MESSAGE_ITEM.slice(Math.max(0, at - 200), at);

    expect(condition).not.toMatch(/isUser\s*&&[^{]*$/);
  });
});
