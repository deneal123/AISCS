import { renderHook, act } from '@testing-library/react';
import { useWebSocketChat } from '@features/chat/model/useWebSocketChat';

jest.mock('@chakra-ui/react', () => ({
  useToast: () => jest.fn(),
}));

describe('useWebSocketChat protocol degradation', () => {
  const originalWebSocket = global.WebSocket;
  const sockets = [];

  class MockWebSocket {
    static OPEN = 1;
    static CONNECTING = 0;

    constructor() {
      this.readyState = MockWebSocket.CONNECTING;
      sockets.push(this);
      setTimeout(() => {
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.();
      }, 0);
    }

    close() {}
    send() {}
  }

  beforeEach(() => {
    sockets.length = 0;
    global.WebSocket = MockWebSocket;
  });

  afterAll(() => {
    global.WebSocket = originalWebSocket;
  });

  // Имена НА ПРОВОДЕ — контракт с бэкендом. Опечатка здесь не падает ни на одной
  // стороне: бэкенд просто не увидит поля (msg.get(...) → None) и молча прогонит
  // ресёрч с настройками по умолчанию, а интерфейс будет показывать выбор
  // пользователя. Поэтому snake_case-имена закреплены тестом.
  it('sends per-user LDR knobs under their wire names', async () => {
    const { result } = renderHook(() => useWebSocketChat('thread-1', {}, true));

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    const sent = [];
    sockets[0].send = (raw) => sent.push(JSON.parse(raw));

    act(() => {
      result.current.sendMessage('исследуй тему', null, null, {
        deepResearch: true,
        ldrModel: 'openai/gpt-4o',
        ldrStrategy: 'focused-iteration',
      });
    });

    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({
      deep_research: true,
      ldr_model: 'openai/gpt-4o',
      ldr_strategy: 'focused-iteration',
    });
  });

  it('omits the strategy entirely when the user kept the default', async () => {
    const { result } = renderHook(() => useWebSocketChat('thread-1', {}, true));

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    const sent = [];
    sockets[0].send = (raw) => sent.push(JSON.parse(raw));

    act(() => {
      result.current.sendMessage('исследуй тему', null, null, { ldrStrategy: '' });
    });

    // Пустая строка НЕ должна уезжать: на бэкенде `or None` её и так погасит, но
    // отправлять «выбор», которого пользователь не делал, — врать о намерении.
    expect(sent[0]).not.toHaveProperty('ldr_strategy');
  });

  it('sends expensive-run consent under the backend wire name', async () => {
    const { result } = renderHook(() => useWebSocketChat('thread-1', {}, true));

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    const sent = [];
    sockets[0].send = (raw) => sent.push(JSON.parse(raw));

    act(() => {
      result.current.sendMessage('изучи архив', null, null, { confirmExpensiveRun: true });
    });

    expect(sent[0]).toMatchObject({ confirm_expensive_run: true });
  });

  it('routes invalid contract events into protocol_error channel and keeps ui alive', async () => {
    const onAgentEvent = jest.fn();
    const onJobCreated = jest.fn();

    renderHook(() => useWebSocketChat('thread-1', { onAgentEvent, onJobCreated }, true));

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    act(() => {
      sockets[0].onmessage({
        data: JSON.stringify({
          type: 'job_created',
          job_id: 'job-1',
          thread_id: 'thread-1',
          metadata: {},
          data: 'broken payload',
        }),
      });
    });

    expect(onJobCreated).not.toHaveBeenCalled();
    expect(onAgentEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: 'protocol_error',
      event_type: 'job_created',
    }));
  });

  // Browser text is selected from bounded codes. Raw provider/backend messages are
  // intentionally ignored because they may contain response bodies or request data.
  const errorShapes = [
    ['agent timeout', {
      type: 'error',
      data: 'PRIVATE_PROVIDER_BODY',
      message: 'PRIVATE_PROVIDER_BODY',
      metadata: { failure_code: 'timeout' },
    }, 'Истекло время ожидания ответа.'],
    ['backend balance code', {
      type: 'error',
      error: 'PRIVATE_BACKEND_EXCEPTION',
      error_code: 'insufficient_funds',
    }, 'Недостаточно средств на балансе.'],
  ];

  it.each(errorShapes)('renders a bounded error label — %s', async (_name, frame, expected) => {
    const onError = jest.fn();

    renderHook(() => useWebSocketChat('thread-1', { onError }, true));

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    act(() => {
      sockets[0].onmessage({ data: JSON.stringify(frame) });
    });

    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: expected }));
  });

  it('still falls back when the frame carries no text at all', async () => {
    const onError = jest.fn();

    renderHook(() => useWebSocketChat('thread-1', { onError }, true));

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    act(() => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'error', metadata: {} }) });
    });

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Выполнение завершилось с ошибкой.' })
    );
  });

  it('drops malformed JSON into the local protocol channel', async () => {
    const onAgentEvent = jest.fn();
    const onError = jest.fn();

    renderHook(() => useWebSocketChat('thread-1', { onAgentEvent, onError }, true));
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 120));
    });

    act(() => sockets[0].onmessage({ data: '{not-json' }));

    expect(onError).not.toHaveBeenCalled();
    expect(onAgentEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: 'protocol_error',
      reason_code: 'invalid_json',
    }));
  });
});
