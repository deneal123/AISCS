import { renderHook, act } from '@testing-library/react';
import { useChatStreamingLifecycle } from '@features/chat/hooks/orchestration/useChatStreamingLifecycle';

describe('useChatStreamingLifecycle', () => {
  it('handles lifecycle callbacks', () => {
    const setIsLoading = jest.fn();
    const setError = jest.fn();
    const appendTraceEvent = jest.fn();
    const finalizeTraceSession = jest.fn();
    const setInputValue = jest.fn();
    const setCurrentJob = jest.fn();
    const clearCurrentJob = jest.fn();
    const addMessage = jest.fn();
    const appendStreamChunk = jest.fn();
    const completeLastAgentMessage = jest.fn();
    const finalizeStreamWithContent = jest.fn();
    const { result } = renderHook(() => useChatStreamingLifecycle({
      setIsLoading, setError, appendTraceEvent, finalizeTraceSession, setInputValue,
      setCurrentJob, clearCurrentJob, addMessage, appendStreamChunk,
      completeLastAgentMessage, finalizeStreamWithContent,
    }));
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j1' }));
    expect(setIsLoading).toHaveBeenCalledWith(true);
    // celeryTaskId кладётся в reducer-job (единый источник для отмены); без него — null.
    expect(setCurrentJob).toHaveBeenCalledWith({ id: 'j1', celeryTaskId: null, status: 'processing', progress: 0 });
    act(() => result.current.actions.wsCallbacks.onError({ message: 'boom' }));
    expect(setError).toHaveBeenCalledWith('Ошибка чата: boom');
  });

  it('captures celery_task_id from job_created into the reducer job (cancel source of truth)', () => {
    const setCurrentJob = jest.fn();
    const noop = jest.fn();
    const { result } = renderHook(() => useChatStreamingLifecycle({
      setIsLoading: noop, setError: noop, appendTraceEvent: noop, finalizeTraceSession: noop,
      setInputValue: noop, setCurrentJob, clearCurrentJob: noop, addMessage: noop,
      appendStreamChunk: noop, completeLastAgentMessage: noop, finalizeStreamWithContent: noop,
    }));
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j2', celery_task_id: 'celery-abc' }));
    expect(setCurrentJob).toHaveBeenCalledWith({ id: 'j2', celeryTaskId: 'celery-abc', status: 'processing', progress: 0 });
  });

  // --- панель «Ход работы» не должна оставаться бегущей над готовым ответом ----------- //

  const makeHook = (overrides = {}) => {
    const spies = {
      setIsLoading: jest.fn(), setError: jest.fn(), appendTraceEvent: jest.fn(),
      finalizeTraceSession: jest.fn(), setInputValue: jest.fn(), setCurrentJob: jest.fn(),
      clearCurrentJob: jest.fn(), addMessage: jest.fn(), appendStreamChunk: jest.fn(),
      completeLastAgentMessage: jest.fn(), finalizeStreamWithContent: jest.fn(),
      ...overrides,
    };
    const { result } = renderHook(() => useChatStreamingLifecycle(spies));
    return { result, spies };
  };

  it('закрывает панель на ПОВТОРНОМ agent_reply, а не только гасит спиннер', () => {
    // 🔴 ЖАЛОБА ВЛАДЕЛЬЦА: ответ на экране, а «Ход работы» навсегда в «Готовлю ответ…».
    // Ветка дедупликации выходила рано: гасила спиннер и НЕ финализировала сессию.
    // Дубль приезжает не редко — переподключение канала, повторная доставка, регенерация.
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j1' }));
    act(() => result.current.actions.wsCallbacks.onAgentReply({ job_id: 'j1', reply: 'готово' }));
    spies.finalizeTraceSession.mockClear();

    act(() => result.current.actions.wsCallbacks.onAgentReply({ job_id: 'j1', reply: 'готово' }));

    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('done');
  });

  it('закрывает панель, когда канал разорван терминально при живой задаче', () => {
    // 🔴 ВТОРОЙ ПУТЬ ТОГО ЖЕ. Замерено на живом стеке: `agent_reply` приходит ПОСЛЕДНИМ,
    // уже после `agent_complete` и `stream_complete`. Разрыв в этом промежутке оставлял
    // ответ на экране (он собран из чанков) и бегущую панель навсегда.
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j1' }));

    act(() => result.current.actions.wsCallbacks.onDisconnect({}, false));

    expect(spies.setIsLoading).toHaveBeenLastCalledWith(false);
    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('done');
  });

  it('НЕ трогает панель на восстановимом реконнекте', () => {
    // 🔴 ГРАНИЦА. Сетевой блик — задача жива, после переподключения приедут и чанки, и
    // финальный ответ. Закрой панель здесь — и человек решит, что ход завершён.
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j1' }));

    act(() => result.current.actions.wsCallbacks.onDisconnect({}, true));

    expect(spies.finalizeTraceSession).not.toHaveBeenCalled();
  });

  it('не закрывает панель, если задачи в работе не было', () => {
    // ⚠️ Закрытие вкладки без активного хода не должно финализировать чужую сессию:
    // переключение треда закрывает сокет штатно, и панель прошлого хода уже закрыта.
    const { result, spies } = makeHook();

    act(() => result.current.actions.wsCallbacks.onDisconnect({}, false));

    expect(spies.finalizeTraceSession).not.toHaveBeenCalled();
  });

  it('честно показывает частичный ответ после дедлайна без сырой ошибки провайдера', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j1' }));

    act(() => result.current.actions.wsCallbacks.onAgentReply({
      job_id: 'j1',
      reply: 'Успел подготовить часть ответа',
      metadata: { execution_status: 'timed_out', provider_error: 'timeout at upstream: internal details' },
    }));

    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'info', title: 'Ответ подготовлен частично',
      detail: 'Время выполнения истекло — показан результат, который агент успел подготовить.',
    }));
    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('done');
  });

  it('показывает безопасный прогресс инструмента из status_update', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      agent_name: 'general',
      metadata: { kind: 'tool_progress', tool_progress: { tool: 'web_search', status: 'succeeded', duration_ms: 42, result_chars: 128 } },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'done', title: 'Завершён: Веб-поиск', detail: '42 мс · результат: 128 симв.',
    }));
  });

  it('показывает reuse без аргументов вызова', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      agent_name: 'general',
      metadata: {
        kind: 'tool_progress',
        tool_progress: {
          tool: 'web_search', status: 'reused', dedup_reason: 'inflight',
          arguments: '{"secret":"must-not-render"}', result_chars: 128,
        },
      },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'done', title: 'Использован сохранённый результат: Веб-поиск', detail: 'результат: 128 симв.',
    }));
    expect(String(spies.appendTraceEvent.mock.calls[0][0])).not.toContain('must-not-render');
  });

  it('объясняет ожидание согласия вместо молчаливого пропуска инструмента', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      metadata: { kind: 'tool_availability', tool_availability: { offered: ['web_search'], omissions: [{ tool: 'watch_video', reason: 'needs_confirmation' }] } },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'offer', title: 'Нужно согласие на инструменты',
    }));
  });

  it('показывает прогрессивное раскрытие инструментов без технических схем', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      agent_name: 'general',
      metadata: {
        kind: 'tool_disclosure',
        tool_disclosure: { mode: 'enforce', stage: 2, candidates: 21, selected: 3, offered: 3 },
      },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'thinking',
      title: 'Инструменты раскрываются по шагам',
      detail: 'Кандидатов: 21 · Выбрано: 3',
    }));
  });

  it('показывает факт выполнения workflow без раскрытия каталога или запроса', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      agent_name: 'router',
      metadata: {
        kind: 'workflow_execution',
        workflow_execution: {
          workflow_id: 'private-id', name: 'workflow_private', cost_class: 'paid', status: 'succeeded',
        },
      },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'done', title: 'Выполнен сохранённый сценарий', detail: '',
    }));
    expect(String(spies.appendTraceEvent.mock.calls[0][0])).not.toContain('private-id');
  });

  it('показывает run integrity без причин, payload или результатов sidecar', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      agent_name: 'transport',
      metadata: {
        kind: 'run_integrity',
        run_integrity: {
          policy: 'first_valid_result',
          anomaly_count: 2,
          reasons: ['duplicate_result', 'event_after_result'],
          result: 'must-not-render',
        },
      },
    }));

    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'info',
      title: 'Поток ответа завершён с защитой',
      detail: 'Служебных отклонений: 2',
    }));
    const trace = spies.appendTraceEvent.mock.calls[0][0];
    expect(String(trace)).not.toContain('duplicate_result');
    expect(String(trace)).not.toContain('must-not-render');
  });

  it('показывает auto-mode только через bounded reason_code', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      agent_name: 'router',
      message: 'Режим выбран',
      metadata: {
        kind: 'auto_decision',
        auto: {
          reason: 'synthetic-model-rationale-must-not-render',
          reason_code: 'model_classification',
        },
      },
    }));

    const trace = spies.appendTraceEvent.mock.calls[0][0];
    expect(trace.detail).toContain('Режим определён по типу задачи');
    expect(String(trace)).not.toContain('synthetic-model-rationale-must-not-render');
  });
});
