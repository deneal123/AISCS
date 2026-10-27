import { renderHook, act } from '@testing-library/react';
import { useChatStreamingLifecycle } from '@features/chat/hooks/orchestration/useChatStreamingLifecycle';

describe('useChatStreamingLifecycle', () => {
  it('does not turn a successful transport into a completed harness task', () => {
    const spies = {
      setIsLoading: jest.fn(), setCurrentJob: jest.fn(), clearCurrentJob: jest.fn(),
      appendTraceEvent: jest.fn(), finalizeTraceSession: jest.fn(), addMessage: jest.fn(),
      finalizeStreamWithContent: jest.fn(),
    };
    const { result } = renderHook(() => useChatStreamingLifecycle(spies));
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'blocked' }));
    act(() => result.current.actions.wsCallbacks.onAgentReply({
      job_id: 'blocked', reply: 'Подтверждённая часть результата',
      metadata: { execution_status: 'completed', task_result: {
        schema_version: 2, status: 'blocked', verified: false, blocker: 'operation_unknown',
      } },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Задача заблокирована', detail: expect.stringContaining('Повторное исполнение заблокировано'),
    }));
    expect(spies.appendTraceEvent).not.toHaveBeenCalledWith(expect.objectContaining({ title: 'Ответ сформирован' }));
    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('done'); // Транспортный terminal не изменён.
  });
  it('parks an offer without streaming or finalizing an answer, and resumes only on another acknowledged job', () => {
    const spies = { setIsLoading: jest.fn(), setCurrentJob: jest.fn(), clearCurrentJob: jest.fn(),
      appendTraceEvent: jest.fn(), finalizeTraceSession: jest.fn(), addMessage: jest.fn(),
      appendStreamChunk: jest.fn(), finalizeStreamWithContent: jest.fn(), setInputValue: jest.fn(),
      markConfirmationAccepted: jest.fn() };
    const { result } = renderHook(() => useChatStreamingLifecycle(spies));
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'pending' }));
    act(() => callbacks.onAgentEvent({ type: 'status_update', job_id: 'pending', metadata: {
      kind: 'mode_offer', mode_offer: { mode: 'deep_research', blocking: true, offer_id: 'opaque' },
    } }));
    act(() => callbacks.onStreamChunk({ job_id: 'pending', data: 'premature answer' }));
    act(() => callbacks.onAgentReply({ job_id: 'pending', reply: 'Waiting', metadata: { awaiting_confirmation: true } }));
    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('awaiting_confirmation');
    expect(spies.appendStreamChunk).not.toHaveBeenCalled();
    expect(spies.finalizeStreamWithContent).not.toHaveBeenCalled();
    expect(spies.addMessage).not.toHaveBeenCalled();
    act(() => callbacks.onJobCreated({ job_id: 'continued', confirmation_status: 'declined', confirmation_offer_id: 'opaque' }));
    act(() => callbacks.onStreamChunk({ job_id: 'continued', data: 'actual answer' }));
    expect(spies.markConfirmationAccepted).toHaveBeenCalledWith('opaque', 'declined');
    expect(spies.appendStreamChunk).toHaveBeenCalledTimes(1);
  });
  it('updates video heartbeat without adding duplicate trace steps or raw payload', () => {
    const appendTraceEvent = jest.fn();
    const updateTraceProgress = jest.fn();
    const { result } = renderHook(() => useChatStreamingLifecycle({ appendTraceEvent, updateTraceProgress }));
    const event = { type: 'status_update', metadata: { kind: 'video_progress',
      video_progress: { stage: 'download', url: 'PRIVATE' } } };
    act(() => result.current.actions.wsCallbacks.onAgentEvent(event));
    act(() => result.current.actions.wsCallbacks.onAgentEvent({ ...event, metadata: {
      ...event.metadata, video_progress: { stage: 'download', heartbeat: true },
    } }));
    expect(updateTraceProgress).toHaveBeenCalledTimes(2);
    expect(appendTraceEvent).toHaveBeenCalledTimes(1);
    expect(appendTraceEvent).toHaveBeenCalledWith({ kind: 'info', title: 'Загружаю видео', timestamp: undefined });
  });
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
    expect(setError).toHaveBeenCalledWith('Выполнение завершилось с ошибкой.');
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
    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('error');
  });

  it('НЕ трогает панель на восстановимом реконнекте', () => {
    // 🔴 ГРАНИЦА. Сетевой блик — задача жива, после переподключения приедут и чанки, и
    // финальный ответ. Закрой панель здесь — и человек решит, что ход завершён.
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'j1' }));

    act(() => result.current.actions.wsCallbacks.onDisconnect({}, true));

    expect(spies.finalizeTraceSession).not.toHaveBeenCalled();
  });

  it('never clears a newer composer draft when a final answer arrives', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onJobCreated({ job_id: 'late-result' }));
    act(() => result.current.actions.wsCallbacks.onAgentReply({ job_id: 'late-result', reply: 'Final result' }));
    // Sending already consumed the submitted draft. Result delivery does not
    // own subsequent edits, including edits after Stop or connection recovery.
    expect(spies.setInputValue).not.toHaveBeenCalled();
  });

  it('does not reopen a finished job or duplicate its answer after a replayed acknowledgement', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'finished' }));
    act(() => callbacks.onAgentReply({ job_id: 'finished', reply: 'Final result' }));
    spies.setIsLoading.mockClear();
    act(() => callbacks.onJobCreated({ job_id: 'finished' }));
    expect(spies.setIsLoading).not.toHaveBeenCalledWith(true);
    act(() => callbacks.onAgentReply({ job_id: 'finished', reply: 'Final result' }));
    expect(spies.finalizeStreamWithContent).toHaveBeenCalledTimes(1);
  });

  it('ignores an old acknowledgement while a newer job is streaming', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'old' }));
    act(() => callbacks.onAgentReply({ job_id: 'old', reply: 'Old result' }));
    act(() => callbacks.onJobCreated({ job_id: 'new' }));
    spies.setCurrentJob.mockClear();
    act(() => callbacks.onJobCreated({ job_id: 'old' }));
    act(() => callbacks.onStreamChunk({ job_id: 'new', data: 'New result' }));
    expect(spies.setCurrentJob).not.toHaveBeenCalled();
    expect(spies.appendStreamChunk).toHaveBeenCalledWith('New result', {});
  });

  it('keeps parked consent frozen when its acknowledgement is replayed', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'offer' }));
    act(() => callbacks.onAgentReply({ job_id: 'offer', metadata: { awaiting_confirmation: true } }));
    spies.setIsLoading.mockClear();
    act(() => callbacks.onJobCreated({ job_id: 'offer' }));
    act(() => callbacks.onStreamChunk({ job_id: 'offer', data: 'Must remain parked' }));
    expect(spies.setIsLoading).not.toHaveBeenCalledWith(true);
    expect(spies.appendStreamChunk).not.toHaveBeenCalled();
  });

  it('enriches a duplicate active acknowledgement with its cancellation task without a second trace step', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'active' }));
    act(() => callbacks.onJobCreated({ job_id: 'active', celery_task_id: 'late-task' }));
    act(() => callbacks.onJobCreated({ job_id: 'active' }));
    expect(spies.setCurrentJob).toHaveBeenLastCalledWith({
      id: 'active', celeryTaskId: 'late-task', status: 'processing', progress: 0,
    });
    expect(spies.appendTraceEvent).toHaveBeenCalledTimes(1);
    expect(spies.setIsLoading).toHaveBeenCalledTimes(1);
  });

  it('preserves an accepted job through a local socket error and consumes replayed chunks', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'accepted', celery_task_id: 'fixture-task' }));
    spies.setIsLoading.mockClear();
    act(() => callbacks.onError({ code: 'transport', localConnectionFailure: true }));
    expect(spies.clearCurrentJob).not.toHaveBeenCalled();
    expect(spies.finalizeTraceSession).not.toHaveBeenCalled();
    expect(spies.setIsLoading).not.toHaveBeenCalledWith(false);
    act(() => callbacks.onDisconnect({}, true));
    act(() => callbacks.onStreamChunk({ job_id: 'accepted', data: 'replayed text' }));
    expect(spies.appendStreamChunk).toHaveBeenCalledWith('replayed text', {});
  });

  it('keeps parked consent intact through a local connection error', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'offer-job' }));
    act(() => callbacks.onAgentReply({ job_id: 'offer-job', reply: 'waiting', metadata: { awaiting_confirmation: true } }));
    spies.finalizeTraceSession.mockClear();
    act(() => callbacks.onError({ code: 'transport', localConnectionFailure: true }));
    expect(spies.finalizeTraceSession).not.toHaveBeenCalled();
  });

  it('does not treat agent stage completion as the final job result', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'accepted' }));
    act(() => callbacks.onAgentComplete({ job_id: 'accepted' }));
    act(() => callbacks.onComplete());
    expect(spies.completeLastAgentMessage).not.toHaveBeenCalled();
    expect(spies.clearCurrentJob).not.toHaveBeenCalled();
    expect(spies.setIsLoading).not.toHaveBeenCalledWith(false);
  });

  it('still finalizes a provider transport failure rather than treating it as socket recovery', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'accepted' }));
    act(() => callbacks.onError({ code: 'transport' }));
    expect(spies.finalizeTraceSession).toHaveBeenCalledWith('error');
    expect(spies.clearCurrentJob).toHaveBeenCalledTimes(1);
  });

  it('does not downgrade an authoritative result after an idle socket error', () => {
    const { result, spies } = makeHook();
    const callbacks = result.current.actions.wsCallbacks;
    act(() => callbacks.onJobCreated({ job_id: 'accepted' }));
    act(() => callbacks.onAgentReply({ job_id: 'accepted', reply: 'Final result' }));
    spies.finalizeTraceSession.mockClear();
    act(() => callbacks.onError({ code: 'transport', localConnectionFailure: true }));
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

  it('не выдаёт ограничения доступности за активный запрос согласия', () => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      metadata: { kind: 'tool_availability', tool_availability: { offered: ['web_search'], omissions: [{ tool: 'watch_video', reason: 'needs_confirmation' }] } },
    }));
    expect(spies.appendTraceEvent).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'info', title: 'Инструменты подготовлены',
      detail: expect.stringContaining('Доступны только с разрешением:'),
    }));
    expect(spies.appendTraceEvent.mock.calls).not.toEqual(expect.arrayContaining([
      [expect.objectContaining({ kind: 'offer' })],
    ]));
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

  it.each(['shortcut_smalltalk', 'shortcut_continue'])('относит shortcut %s только к выбору режима', (reasonCode) => {
    const { result, spies } = makeHook();
    act(() => result.current.actions.wsCallbacks.onAgentEvent({
      type: 'status_update',
      metadata: { kind: 'auto_decision', auto: { source: 'shortcut', reason_code: reasonCode } },
    }));
    const trace = spies.appendTraceEvent.mock.calls[0][0];
    expect(trace.detail).toContain('Выбор режима — без вызова модели');
    expect(trace.detail).not.toContain('сообщение обработано без вызова модели');
    expect(trace.detail).not.toContain('ответа обработано без вызова модели');
    expect(spies.appendStreamChunk).not.toHaveBeenCalled();
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
