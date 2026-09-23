import { useMemo, useReducer } from 'react';

export const CHAT_ACTIONS = {
  ADD_MESSAGE: 'ADD_MESSAGE', CLEAR_MESSAGES: 'CLEAR_MESSAGES', REPLACE_MESSAGES: 'REPLACE_MESSAGES', LOAD_HISTORY: 'LOAD_HISTORY',
  SET_CURRENT_JOB: 'SET_CURRENT_JOB', CLEAR_JOB: 'CLEAR_JOB',
  SET_LOADING: 'SET_LOADING', SET_ERROR: 'SET_ERROR', CLEAR_ERROR: 'CLEAR_ERROR', CLEAR_THREAD: 'CLEAR_THREAD',
  STREAM_APPEND_CHUNK: 'STREAM_APPEND_CHUNK', STREAM_COMPLETE_LAST_AGENT: 'STREAM_COMPLETE_LAST_AGENT', STREAM_FINALIZE_WITH_CONTENT: 'STREAM_FINALIZE_WITH_CONTENT',
};

export const initialChatState = {
  messages: [], currentJob: null, loading: false, error: null,
};

export function chatStateReducer(state, action) { switch (action.type) {
  // Сообщение с УЖЕ ИЗВЕСТНЫМ id заменяет прежнее, а не добавляется вторым. Нужно для
  // отправки: реплика пользователя показывается СРАЗУ, а разбор приложенных к ней ссылок
  // приходит через несколько секунд и дописывает ей источники. Без замены человек ждал бы
  // сеть, чтобы увидеть собственное сообщение (жалоба: «фриз на минуту, в чат ничего не
  // отправилось»), либо видел бы его дважды.
  case CHAT_ACTIONS.ADD_MESSAGE: {
    const id = action.payload?.id;
    const at = id == null ? -1 : state.messages.findIndex((m) => m.id === id);
    if (at < 0) return { ...state, messages: [...state.messages, action.payload] };
    const messages = state.messages.slice();
    messages[at] = action.payload;
    return { ...state, messages };
  }
  case CHAT_ACTIONS.CLEAR_MESSAGES: return { ...state, messages: [] };
  case CHAT_ACTIONS.REPLACE_MESSAGES: return { ...state, messages: Array.isArray(action.payload) ? action.payload : [] };
  case CHAT_ACTIONS.LOAD_HISTORY: {
    const payload = Array.isArray(action.payload) ? action.payload : [];
    const realtimeMsgs = state.messages.filter((m) => !String(m.id ?? '').startsWith('hist_'));
    return { ...state, messages: [...payload, ...realtimeMsgs] };
  }
  case CHAT_ACTIONS.SET_CURRENT_JOB: return { ...state, currentJob: action.payload };
  case CHAT_ACTIONS.CLEAR_JOB: return { ...state, currentJob: null };
  case CHAT_ACTIONS.SET_LOADING: return { ...state, loading: action.payload };
  case CHAT_ACTIONS.SET_ERROR: return { ...state, error: action.payload };
  case CHAT_ACTIONS.CLEAR_ERROR: return { ...state, error: null };
  case CHAT_ACTIONS.CLEAR_THREAD: return { ...state, messages: [], currentJob: null, error: null };
  case CHAT_ACTIONS.STREAM_APPEND_CHUNK: {
    const chunk = action.payload?.chunk || '';
    const metadata = action.payload?.metadata || {};
    if (!chunk.trim()) return state;
    const last = state.messages[state.messages.length - 1];
    if (last && last.type === 'agent' && !last.complete) {
      const content = `${last.content}${chunk}`;
      return {
        ...state,
        messages: state.messages.map((msg, index) => index === state.messages.length - 1 ? { ...msg, content, streaming: true, typingProgress: Math.min(1, content.length / 1000), metadata: { ...(msg.metadata || {}), ...metadata } } : msg),
      };
    }
    return {
      ...state,
      messages: [...state.messages, { id: `agent_${Date.now()}_${Math.random()}`, type: 'agent', content: chunk, timestamp: new Date().toISOString(), metadata, complete: false, streaming: true, isTyping: true, typingProgress: 0 }],
    };
  }
  case CHAT_ACTIONS.STREAM_COMPLETE_LAST_AGENT:
    return {
      ...state,
      messages: state.messages.map((msg, index) => (index === state.messages.length - 1 && msg.type === 'agent' && msg.isTyping ? { ...msg, isTyping: false, complete: true, typingProgress: 1 } : msg)),
    };
  case CHAT_ACTIONS.STREAM_FINALIZE_WITH_CONTENT: {
    const { content, metadata, file_url } = action.payload;
    const msgs = state.messages;
    // Находим активное стриминговое сообщение агента. Флаг `streaming` ставится
    // в STREAM_APPEND_CHUNK и снимается только здесь — поэтому даже если гонка
    // (agent_complete пришёл раньше agent_reply) уже пометила сообщение
    // `complete`, мы всё равно дописываем финальный текст В ЭТО ЖЕ сообщение,
    // а не создаём второй «пузырь». Идём с конца — берём самое свежее.
    let idx = -1;
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      if (msgs[i].type === 'agent' && msgs[i].streaming) { idx = i; break; }
    }
    // Фоллбэк: хвостовое незавершённое сообщение агента без явного флага
    // (путь без чанков — стрима не было, сразу пришёл agent_reply).
    if (idx === -1) {
      const lastIdx = msgs.length - 1;
      if (lastIdx >= 0 && msgs[lastIdx].type === 'agent' && !msgs[lastIdx].complete) idx = lastIdx;
    }
    if (idx >= 0) {
      return {
        ...state,
        messages: msgs.map((msg, i) => i === idx ? { ...msg, content, metadata: metadata || msg.metadata, file_url: file_url || msg.file_url, complete: true, isTyping: false, streaming: false, typingProgress: 1 } : msg),
      };
    }
    return {
      ...state,
      messages: [...msgs, { id: `agent_${Date.now()}_${Math.random()}`, type: 'agent', content, timestamp: new Date().toISOString(), metadata, file_url, complete: true, isTyping: false, streaming: false, typingProgress: 1 }],
    };
  }
  default: return state;
}}

export function useChatStateContainer() {
  const [state, dispatch] = useReducer(chatStateReducer, initialChatState);
  return useMemo(() => ({ state, dispatch }), [state, dispatch]);
}
