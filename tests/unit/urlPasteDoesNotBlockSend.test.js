/**
 * 🔴 Вставка промпта со ссылкой замораживала отправку.
 *
 * Разбор ссылки — это сеть, и он стоял ПЕРЕД показом реплики: человек вставлял текст и на
 * минуту получал замерший интерфейс, в котором его сообщения не было вовсе, а потом сразу
 * сообщение с ошибкой. Два правила, и оба проверяются здесь: реплику можно показать
 * заранее и дополнить на месте, а у чтения ссылки есть граница.
 */
import { CHAT_ACTIONS, chatStateReducer, initialChatState } from '@/features/chat/model/chatStateContainer';
import { withDeadline } from '@/features/chat/hooks/orchestration/useChatMessageSender';

describe('реплика показывается до разбора ссылок', () => {
  it('сообщение с тем же id ЗАМЕНЯЕТ прежнее, а не добавляется вторым', () => {
    const first = { id: 'm1', type: 'user', content: 'смотри https://example.test' };
    const withSources = {
      ...first,
      metadata: { sources: [{ url: 'https://example.test', ok: true }] },
    };

    let state = chatStateReducer(initialChatState, {
      type: CHAT_ACTIONS.ADD_MESSAGE,
      payload: first,
    });
    state = chatStateReducer(state, { type: CHAT_ACTIONS.ADD_MESSAGE, payload: withSources });

    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].metadata.sources).toHaveLength(1);
  });

  it('разные сообщения по-прежнему копятся', () => {
    let state = chatStateReducer(initialChatState, {
      type: CHAT_ACTIONS.ADD_MESSAGE,
      payload: { id: 'm1', content: 'а' },
    });
    state = chatStateReducer(state, {
      type: CHAT_ACTIONS.ADD_MESSAGE,
      payload: { id: 'm2', content: 'б' },
    });

    expect(state.messages.map((m) => m.id)).toEqual(['m1', 'm2']);
  });

  it('сообщение без id добавляется, а не схлопывается с другим безымянным', () => {
    let state = chatStateReducer(initialChatState, {
      type: CHAT_ACTIONS.ADD_MESSAGE,
      payload: { content: 'а' },
    });
    state = chatStateReducer(state, { type: CHAT_ACTIONS.ADD_MESSAGE, payload: { content: 'б' } });

    expect(state.messages).toHaveLength(2);
  });
});

describe('у чтения ссылки есть граница', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('неотвечающий источник отваливается по дедлайну, а не ждёт до упора', async () => {
    const never = new Promise(() => {});
    const settled = withDeadline(never, 1000).then(
      () => 'ответ пришёл',
      (e) => e.message
    );

    jest.advanceTimersByTime(1200);

    await expect(settled).resolves.toMatch(/не ответил/);
  });

  it('успевший ответ проходит как есть', async () => {
    await expect(withDeadline(Promise.resolve({ content: 'текст' }), 1000)).resolves.toEqual({
      content: 'текст',
    });
  });
});
