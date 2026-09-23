import {
  chatStateReducer as chatReducer,
  CHAT_ACTIONS,
  initialChatState as initialState,
} from '@features/chat/model/chatStateContainer';

describe('chat reducer public behavior', () => {
  it('adds messages and replaces/clears them', () => {
    const added = chatReducer(initialState, {
      type: CHAT_ACTIONS.ADD_MESSAGE,
      payload: { id: 'm1', content: 'hello' },
    });
    expect(added.messages).toHaveLength(1);

    const replaced = chatReducer(added, {
      type: CHAT_ACTIONS.REPLACE_MESSAGES,
      payload: [{ id: 'm2', content: 'world' }],
    });
    expect(replaced.messages).toHaveLength(1);
    expect(replaced.messages[0].id).toBe('m2');

    const cleared = chatReducer(replaced, { type: CHAT_ACTIONS.CLEAR_MESSAGES });
    expect(cleared.messages).toHaveLength(0);
  });

  it('merges history before realtime messages', () => {
    const withRealtime = chatReducer(initialState, {
      type: CHAT_ACTIONS.ADD_MESSAGE,
      payload: { id: 'live_1', content: 'live' },
    });
    const merged = chatReducer(withRealtime, {
      type: CHAT_ACTIONS.LOAD_HISTORY,
      payload: [{ id: 'hist_0', content: 'past' }],
    });
    expect(merged.messages.map((m) => m.id)).toEqual(['hist_0', 'live_1']);
  });

  it('handles job lifecycle', () => {
    const withJob = chatReducer(initialState, {
      type: CHAT_ACTIONS.SET_CURRENT_JOB,
      payload: { id: 'j1', status: 'processing' },
    });
    expect(withJob.currentJob.id).toBe('j1');

    const cleared = chatReducer(withJob, { type: CHAT_ACTIONS.CLEAR_JOB });
    expect(cleared.currentJob).toBeNull();
  });

  it('tracks loading and error flags', () => {
    const loading = chatReducer(initialState, { type: CHAT_ACTIONS.SET_LOADING, payload: true });
    expect(loading.loading).toBe(true);

    const errored = chatReducer(loading, { type: CHAT_ACTIONS.SET_ERROR, payload: 'boom' });
    expect(errored.error).toBe('boom');

    const clearedErr = chatReducer(errored, { type: CHAT_ACTIONS.CLEAR_ERROR });
    expect(clearedErr.error).toBeNull();
  });

  it('clears thread state (messages, trace, job, error)', () => {
    const dirty = chatReducer(
      { ...initialState, messages: [{ id: 'm1' }], error: 'x', currentJob: { id: 'j1' } },
      { type: CHAT_ACTIONS.CLEAR_THREAD },
    );
    expect(dirty.messages).toHaveLength(0);
    expect(dirty.currentJob).toBeNull();
    expect(dirty.error).toBeNull();
  });
});
