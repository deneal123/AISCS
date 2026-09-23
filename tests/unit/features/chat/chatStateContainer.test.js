import { CHAT_ACTIONS, chatStateReducer, initialChatState } from '@features/chat/model/chatStateContainer';

describe('chatStateContainer transitions', () => {
  // Живой trace-механизм — отдельный хук useTraceSessions (свой useState); в
  // редьюсере trace-слайса больше нет (был мёртвым дублем), поэтому здесь его не тестируем.
  it('clears thread state', () => {
    const prev = {
      ...initialChatState,
      messages: [{ id: 'm1' }],
      currentJob: { id: 'job1' },
      error: 'error',
    };
    const next = chatStateReducer(prev, { type: CHAT_ACTIONS.CLEAR_THREAD });
    expect(next.messages).toEqual([]);
    expect(next.currentJob).toBeNull();
    expect(next.error).toBeNull();
  });

  it('LOAD_HISTORY replaces hist_ messages but preserves realtime WS messages', () => {
    const prev = {
      ...initialChatState,
      messages: [
        { id: 'hist_0_2025', content: 'old history' },
        { id: 'agent_1234_0.5', content: 'realtime ws reply' },
      ],
    };
    const historyPayload = [
      { id: 'hist_0_2025', content: 'history msg 1' },
      { id: 'hist_1_2025', content: 'history msg 2' },
    ];
    const next = chatStateReducer(prev, { type: CHAT_ACTIONS.LOAD_HISTORY, payload: historyPayload });

    expect(next.messages).toHaveLength(3);
    expect(next.messages[0].id).toBe('hist_0_2025');
    expect(next.messages[1].id).toBe('hist_1_2025');
    expect(next.messages[2].id).toBe('agent_1234_0.5');
  });

  it('LOAD_HISTORY with no existing realtime messages just sets history', () => {
    const historyPayload = [{ id: 'hist_0_ts', content: 'msg' }];
    const next = chatStateReducer(initialChatState, { type: CHAT_ACTIONS.LOAD_HISTORY, payload: historyPayload });
    expect(next.messages).toEqual(historyPayload);
  });

  it('STREAM_FINALIZE updates the streaming bubble in place (no duplicate) even after STREAM_COMPLETE race', () => {
    // chunk -> создаётся стриминговое сообщение
    let state = chatStateReducer(initialChatState, {
      type: CHAT_ACTIONS.STREAM_APPEND_CHUNK,
      payload: { chunk: 'Hello', metadata: {} },
    });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].streaming).toBe(true);

    // ГОНКА: agent_complete помечает сообщение complete ДО agent_reply
    state = chatStateReducer(state, { type: CHAT_ACTIONS.STREAM_COMPLETE_LAST_AGENT });
    expect(state.messages[0].complete).toBe(true);
    expect(state.messages[0].streaming).toBe(true);

    // finalize должен дописать в ТО ЖЕ сообщение, а не добавить второй пузырь
    state = chatStateReducer(state, {
      type: CHAT_ACTIONS.STREAM_FINALIZE_WITH_CONTENT,
      payload: { content: 'Hello world', metadata: { agent_name: 'general' } },
    });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].content).toBe('Hello world');
    expect(state.messages[0].streaming).toBe(false);
    expect(state.messages[0].complete).toBe(true);
  });

  it('STREAM_FINALIZE appends a bubble when there was no streaming message (chunk-less path)', () => {
    const next = chatStateReducer(initialChatState, {
      type: CHAT_ACTIONS.STREAM_FINALIZE_WITH_CONTENT,
      payload: { content: 'Direct reply', metadata: {} },
    });
    expect(next.messages).toHaveLength(1);
    expect(next.messages[0].content).toBe('Direct reply');
    expect(next.messages[0].complete).toBe(true);
  });
});
