import { useCallback, useEffect, useMemo, useRef } from 'react';
import { clampTraceDetail, getOmissionReason, getTraceName } from '../../utils/trace';
import { autoModeReasonLabel } from '../../utils/autoModeReason';
import { parseThinking } from '../../utils/thinking';
import { notifyBillingRefresh } from '../../../billing/context/BillingContext';
import { presentDocumentStatus } from '../../model/documentStatus';
import { presentVideoProgress } from '../../model/videoProgress';
import { safeErrorMessage } from '../../model/wsProtocol';
import { presentTaskResult } from '../../model/taskResult';

export function useChatStreamingLifecycle({ isLoading, setIsLoading, setError, appendTraceEvent, updateTraceProgress, markConfirmationAccepted, finalizeTraceSession, addMessage, appendStreamChunk, completeLastAgentMessage, finalizeStreamWithContent, setCurrentJob, clearCurrentJob, onContextCompacted, onWorkspaceInvalidated }) {
  const isLoadingRef = useRef(false);
  const activeWsJobIdRef = useRef('');
  const documentProjectRef = useRef('');
  const lastWsReplyFingerprintRef = useRef('');
  const videoStageRef = useRef('');
  const awaitingDecisionRef = useRef(false);
  const acceptedRunRef = useRef(false);
  const connectionWarningRef = useRef(false);
  // Acknowledgements can be replayed after completion or during a newer job.
  // Keep a bounded, private latch; a replay must not reopen loading or consent.
  const acknowledgedJobsRef = useRef(new Map());

  useEffect(() => {
    isLoadingRef.current = isLoading;
    if (isLoading === false) acceptedRunRef.current = false;
  }, [isLoading]);

  const resolveWsEventJobId = useCallback((payload) => String(payload?.job_id || payload?.metadata?.job_id || '').trim(), []);

  const shouldIgnoreWsEvent = useCallback((payload) => {
    const incomingJobId = resolveWsEventJobId(payload);
    if (!incomingJobId) return false;
    const activeJobId = String(activeWsJobIdRef.current || '').trim();
    if (!activeJobId) {
      activeWsJobIdRef.current = incomingJobId;
      return false;
    }
    return activeJobId !== incomingJobId;
  }, [resolveWsEventJobId]);

  const onJobCreated = useCallback((data) => {
    const incomingJobId = resolveWsEventJobId(data);
    const knownJob = acknowledgedJobsRef.current.get(incomingJobId);
    if (knownJob) {
      // The initial acknowledgement may omit the cancellation task identifier.
      // Enrich only the still-running job, never a completed or parked one.
      if (activeWsJobIdRef.current === incomingJobId && acceptedRunRef.current
        && isLoadingRef.current && !knownJob.celeryTaskId && data?.celery_task_id) {
        const enrichedJob = { ...knownJob, celeryTaskId: data.celery_task_id };
        acknowledgedJobsRef.current.set(incomingJobId, enrichedJob);
        setCurrentJob(enrichedJob);
      }
      return;
    }
    const job = incomingJobId
      ? { id: incomingJobId, celeryTaskId: data?.celery_task_id || null, status: 'processing', progress: 0 }
      : null;
    if (job) {
      acknowledgedJobsRef.current.set(incomingJobId, job);
      if (acknowledgedJobsRef.current.size > 64) {
        acknowledgedJobsRef.current.delete(acknowledgedJobsRef.current.keys().next().value);
      }
    }
    if (incomingJobId) {
      documentProjectRef.current = data?.document_project || '';
      activeWsJobIdRef.current = incomingJobId;
      lastWsReplyFingerprintRef.current = '';
      videoStageRef.current = '';
      awaitingDecisionRef.current = false;
    }
    // Гейт onStreamChunk читает isLoadingRef СИНХРОННО. Эффект [isLoading] обновляет
    // ref только после коммита — если первый stream_chunk приходит в том же тике, что
    // job_created, ref ещё false и токен теряется. Ставим ref здесь же, до чанков.
    isLoadingRef.current = true;
    acceptedRunRef.current = true;
    connectionWarningRef.current = false;
    // celeryTaskId кладём В reducer-job — единый источник для отмены (cancelJob),
    // чтобы не держать вторую копию currentJob в WS-транспорте.
    setCurrentJob(job);
    if (['accepted', 'declined'].includes(data?.confirmation_status)) {
      markConfirmationAccepted?.(data.confirmation_offer_id || null, data.confirmation_status);
    }
    setIsLoading(true);
    appendTraceEvent({ kind: 'info', title: 'Запуск поставлен в очередь', detail: 'Сервер принял запрос. Ожидаю начала обработки.' });
  }, [appendTraceEvent, markConfirmationAccepted, resolveWsEventJobId, setCurrentJob, setIsLoading]);

  // Agent-stage completion is not the authoritative result of the server job.
  const onComplete = useCallback(() => { notifyBillingRefresh(); }, []);

  // The socket closes intentionally (code 1000) on thread switch / unmount without a
  // reconnect, so if a job was still in flight the composer would otherwise stay
  // disabled forever — clear the in-flight state instead of waiting for an event
  // that will never arrive on the old connection.
  const onDisconnect = useCallback((_event, willReconnect) => {
    // Восстановимый реконнект (сетевой блик, зомби-сокет) — НЕ гасим job/loading: серверная
    // задача жива, после переподключения реиграются stream_chunk и финальный agent_reply.
    // Гасим только терминальный разрыв (code=1000 или исчерпаны попытки). Иначе UI показывал
    // «свободен» при живой задаче: композер разблокировался (можно отправить второе сообщение
    // поверх), кнопка отмены пропадала, а реиграемые чанки отбрасывал loading-гейт.
    if (willReconnect) return;
    if (isLoadingRef.current) {
      clearCurrentJob();
      setIsLoading(false);
      acceptedRunRef.current = false;
      isLoadingRef.current = false;
      // 🔴 ПАНЕЛЬ ЗАКРЫВАЕТСЯ ВМЕСТЕ СО СПИННЕРОМ. Терминальное событие `agent_reply`
      // приходит ПОСЛЕДНИМ — уже после `agent_complete` и `stream_complete` (замерено на
      // живом стеке). Разорвись канал в этом промежутке — ответ на экране есть (он собран
      // из чанков), а «Ход работы» навсегда оставался в «Готовлю ответ…». Гасить спиннер и
      // оставлять панель бегущей — значит показывать два противоположных состояния разом.
      appendTraceEvent({ kind: 'error', title: 'Соединение не восстановлено', detail: 'Итог выполнения пока неизвестен. Обновите чат, чтобы проверить результат. Запрос повторно не отправлялся.' });
      finalizeTraceSession('error');
    }
  }, [appendTraceEvent, clearCurrentJob, finalizeTraceSession, setIsLoading]);

  const onError = useCallback((err) => {
    if (err?.localConnectionFailure === true && !isLoadingRef.current && lastWsReplyFingerprintRef.current) {
      setError(safeErrorMessage(err));
      return;
    }
    if (err?.localConnectionFailure === true && (
      (acceptedRunRef.current && isLoadingRef.current && !awaitingDecisionRef.current)
      || (awaitingDecisionRef.current && !isLoadingRef.current)
    )) {
      if (!connectionWarningRef.current) appendTraceEvent({ kind: 'info', title: 'Восстанавливаю связь с чатом', detail: 'Состояние выполнения пока не подтверждено. Запрос повторно не отправляется.' });
      connectionWarningRef.current = true;
      return;
    }
    acceptedRunRef.current = false;
    isLoadingRef.current = false;
    const message = safeErrorMessage(err);
    appendTraceEvent({ kind: 'error', title: 'Ошибка канала обработки', detail: message });
    finalizeTraceSession('error');
    setError(message);
    clearCurrentJob();
    setIsLoading(false);
  }, [appendTraceEvent, clearCurrentJob, finalizeTraceSession, setError, setIsLoading]);

  const onStreamChunk = useCallback((data) => {
    // Отбрасываем только полностью пустые чанки; whitespace/'\n' значимы для markdown
    // (переносы строк, разделители абзацев) — их терять нельзя.
    const chunk = data?.data;
    if (!isLoadingRef.current || awaitingDecisionRef.current || shouldIgnoreWsEvent(data) || chunk == null || chunk === '') return;
    const chunkMeta = { ...(data.metadata || {}),
      ...(documentProjectRef.current ? { document_project: documentProjectRef.current } : {}),
    };
    connectionWarningRef.current = false;
    appendStreamChunk(chunk, chunkMeta);
  }, [appendStreamChunk, shouldIgnoreWsEvent]);

  const onAgentReply = useCallback((data) => {
    if (shouldIgnoreWsEvent(data)) return;
    acceptedRunRef.current = false;
    connectionWarningRef.current = false;
    isLoadingRef.current = false;
    if (data.metadata?.awaiting_confirmation) {
      awaitingDecisionRef.current = true;
      isLoadingRef.current = false;
      clearCurrentJob();
      setIsLoading(false);
      finalizeTraceSession('awaiting_confirmation');
      return;
    }
    if (!data.reply || !data.reply.trim()) {
      finalizeTraceSession('error');
      clearCurrentJob();
      setIsLoading(false);
      return;
    }
    const incomingReply = data.reply.trim();
    const executionStatus = data?.metadata?.execution_status
      || (data?.metadata?.provider_unavailable ? 'failed'
        : data?.metadata?.deadline_exceeded ? 'timed_out'
          : data?.metadata?.partial_failure ? 'partial' : 'completed');
    const taskResult = presentTaskResult(data?.metadata?.task_result);
    const responseTrace = taskResult
      ? { kind: taskResult.kind, title: taskResult.title, detail: taskResult.detail }
      : executionStatus === 'failed'
      ? { kind: 'error', title: 'Ответ сформирован в деградированном режиме', detail: 'Не удалось получить полный ответ от провайдера.' }
      : executionStatus === 'timed_out'
        ? { kind: 'info', title: 'Ответ подготовлен частично', detail: 'Время выполнения истекло — показан результат, который агент успел подготовить.' }
        : executionStatus === 'partial'
          ? { kind: 'info', title: 'Ответ подготовлен частично', detail: 'Часть шагов не завершилась; доступный результат сохранён.' }
          : executionStatus === 'waiting_user'
            ? { kind: 'info', title: 'Нужен ваш ответ', detail: 'Работа приостановлена до ответа на вопрос агента.' }
            : { kind: 'done', title: 'Ответ сформирован', detail: '' };
    const incomingJobId = resolveWsEventJobId(data) || String(activeWsJobIdRef.current || '').trim() || 'unknown_job';
    const replyFingerprint = `${incomingJobId}::${incomingReply}`;
    if (lastWsReplyFingerprintRef.current === replyFingerprint) {
      // 🔴 ПОВТОР ГАСИЛ СПИННЕР, НО НЕ ЗАКРЫВАЛ ПАНЕЛЬ. Ответ уже на экране, а «Ход
      // работы» навсегда оставался в «Готовлю ответ…» — ровно то, что видел владелец.
      // Дубль приезжает не редко: переподключение канала, повторная доставка задачи,
      // регенерация того же ответа. Финализация ИДЕМПОТЕНТНА, и повторный вызов ничего
      // не портит; а вот его отсутствие оставляет живой спиннер над готовым ответом.
      clearCurrentJob();
      setIsLoading(false);
      finalizeTraceSession(executionStatus === 'failed' ? 'error' : 'done');
      return;
    }
    lastWsReplyFingerprintRef.current = replyFingerprint;
    notifyBillingRefresh();
    // Рассуждения модели (<think>...</think>) выносим отдельным шагом в trace,
    // чтобы они не «протекали» в тело ответа, но оставались видимы в «Ходе рассуждения».
    const { reasoning } = parseThinking(incomingReply);
    if (reasoning) {
      appendTraceEvent({ kind: 'thinking', title: 'Размышления модели', detail: reasoning, agent: data?.metadata?.agent_name, timestamp: data?.metadata?.timestamp });
    }
    appendTraceEvent(responseTrace);
    // Finalize the streaming message with authoritative final content rather than adding a second bubble.
    // Falls back to addMessage if no streaming message exists (e.g. chunk-less path).
    if (finalizeStreamWithContent) {
      finalizeStreamWithContent(incomingReply, data.metadata, data.file_url);
    } else {
      addMessage({ id: `agent_${Date.now()}_${Math.random()}`, type: 'agent', content: incomingReply, timestamp: new Date().toISOString(), metadata: data.metadata, file_url: data.file_url, complete: true, isTyping: false, typingProgress: 1 });
    }
    // Ответ получен — задача завершена: гасим индикатор обработки и спиннер.
    clearCurrentJob();
    setIsLoading(false);
    finalizeTraceSession(executionStatus === 'failed' ? 'error' : 'done');
  }, [addMessage, appendTraceEvent, clearCurrentJob, finalizeStreamWithContent, finalizeTraceSession, resolveWsEventJobId, setIsLoading, shouldIgnoreWsEvent]);

  const onAgentComplete = useCallback((data) => {
    if (shouldIgnoreWsEvent(data)) return;
    if (acceptedRunRef.current) return;
    completeLastAgentMessage();
  }, [completeLastAgentMessage, shouldIgnoreWsEvent]);

  const onAgentEvent = useCallback((event) => {
    if (!event?.type || shouldIgnoreWsEvent(event)) return;
    // Чисто-учётное событие: под-шаги мульти-интента пробрасывают наверх свой
    // token_usage отдельным STATUS_UPDATE (иначе billing недосчитывал под-агентские
    // вызовы). Для пользователя это шум — в трейс не выводим.
    if (event.metadata?.kind === 'multi_intent_usage') return;
    if (event.type === 'status_update' && event.metadata?.kind === 'video_progress') {
      const progress = presentVideoProgress(event.metadata.video_progress);
      if (!progress) return;
      updateTraceProgress?.(null, progress.label);
      if (!progress.heartbeat && videoStageRef.current !== progress.label) {
        appendTraceEvent({ kind: 'info', title: progress.label, timestamp: event.timestamp });
      }
      videoStageRef.current = progress.label;
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'workspace_invalidation') {
      // Stream carries only an invalidation code; file and issue content always
      // stays behind the authenticated workspace REST endpoints.
      onWorkspaceInvalidated?.(event.metadata.workspace_invalidation || {});
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'document_status') {
      const presentation = presentDocumentStatus(event.metadata.document_status || {});
      appendTraceEvent({
        ...presentation,
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Компактизация контекста — НЕЗАВИСИМОЕ действие (клик по кольцу), а НЕ часть трейса
    // сообщения. Раньше её события падали в трейс активной сессии и «появлялись во время
    // сообщения». Обратная связь теперь тостами + разделителем/шторкой (ChatPageContainer).
    if (event.type === 'compact_started') {
      return;  // старт показываем тостом на клике, трейс не засоряем
    }
    if (event.type === 'context_compacted') {
      // Только УСПЕШНОЕ сжатие что-то меняет; колбэк сам решает по ok (тост + разделитель
      // + падение кольца при ok, тост «нечего сжимать» при !ok).
      onContextCompacted?.(event, Boolean(event.ok));
      return;
    }
    // Единый lifecycle инструментов приходит аддитивными STATUS_UPDATE. Не показываем
    // аргументы/сырой результат: агент передаёт только безопасную сводку и счётчики.
    if (event.type === 'status_update' && event.metadata?.kind === 'tool_availability') {
      const availability = event.metadata.tool_availability || {};
      const offered = Array.isArray(availability.offered) ? availability.offered : [];
      const omissions = Array.isArray(availability.omissions) ? availability.omissions : [];
      const confirmation = omissions.filter((item) => item?.reason === 'needs_confirmation');
      appendTraceEvent({
        // Availability describes policy, not an anchored confirmation offer.
        // Only a real offer may claim that the run is waiting for a decision.
        kind: 'info',
        title: 'Инструменты подготовлены',
        detail: [
          offered.length ? `Доступно: ${offered.map((tool) => getTraceName(tool)).join(', ')}` : null,
          confirmation.length ? `Доступны только с разрешением: ${confirmation.map((item) => getTraceName(item.tool)).join(', ')}` : null,
          omissions.length && !confirmation.length
            ? `Недоступно: ${omissions.map((item) => `${getTraceName(item.tool)} — ${getOmissionReason(item.reason)}`).join(', ')}`
            : null,
        ].filter(Boolean).join(' · '),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'tool_disclosure') {
      const disclosure = event.metadata.tool_disclosure || {};
      const fallback = disclosure.fallback_reason;
      appendTraceEvent({
        kind: fallback ? 'info' : 'thinking',
        title: fallback ? 'Полный набор инструментов сохранён' : 'Инструменты раскрываются по шагам',
        detail: [
          typeof disclosure.candidates === 'number' ? `Кандидатов: ${disclosure.candidates}` : null,
          typeof disclosure.selected === 'number' ? `Выбрано: ${disclosure.selected}` : null,
          disclosure.schema_tokens_saved ? `схем сэкономлено: ${disclosure.schema_tokens_saved} ток.` : null,
          fallback ? `Причина fallback: ${fallback}` : null,
        ].filter(Boolean).join(' · '),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'tool_plan') {
      const plan = event.metadata.tool_plan || {};
      appendTraceEvent({
        kind: 'plan',
        title: `Раунд инструментов ${plan.round || 1}`,
        detail: Array.isArray(plan.tools) ? plan.tools.map((tool) => getTraceName(tool)).join(', ') : '',
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'tool_progress') {
      const progress = event.metadata.tool_progress || {};
      const status = progress.status || 'running';
      const title = status === 'running'
        ? `Выполняется: ${getTraceName(progress.tool)}`
        : status === 'succeeded'
          ? `Завершён: ${getTraceName(progress.tool)}`
          : status === 'reused'
            ? `Использован сохранённый результат: ${getTraceName(progress.tool)}`
          : status === 'skipped'
            ? 'Вызов инструмента пропущен'
            : `Не выполнен: ${getTraceName(progress.tool)}`;
      appendTraceEvent({
        kind: status === 'failed' ? 'error' : ['succeeded', 'reused'].includes(status) ? 'done' : 'info',
        title,
        detail: [
          progress.reason,
          typeof progress.duration_ms === 'number' ? `${progress.duration_ms} мс` : null,
          typeof progress.result_chars === 'number' ? `результат: ${progress.result_chars} симв.` : null,
          progress.compacted ? 'результат сжат' : null,
        ].filter(Boolean).join(' · '),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'tool_summary') {
      const summary = event.metadata.tool_summary || {};
      appendTraceEvent({
        kind: summary.failed || summary.round_cap_reached ? 'info' : 'done',
        title: summary.partial_success ? 'Инструменты выполнены частично' : 'Работа с инструментами завершена',
        detail: [
          `успешно: ${summary.succeeded || 0}`,
          summary.failed ? `ошибки: ${summary.failed}` : null,
          summary.reused ? `повторно использовано: ${summary.reused}` : null,
          summary.skipped ? `пропущено: ${summary.skipped}` : null,
          summary.round_cap_reached ? 'достигнут лимит шагов' : null,
          summary.deadline_finalized ? 'ответ финализирован по дедлайну' : null,
        ].filter(Boolean).join(' · '),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'run_integrity') {
      const integrity = event.metadata.run_integrity || {};
      appendTraceEvent({
        kind: 'info',
        title: 'Поток ответа завершён с защитой',
        detail: typeof integrity.anomaly_count === 'number'
          ? `Служебных отклонений: ${integrity.anomaly_count}`
          : 'Обнаружены служебные отклонения протокола',
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    if (event.type === 'status_update' && event.metadata?.kind === 'integration_health') {
      const health = event.metadata.integration_health || {};
      appendTraceEvent({
        kind: health.skipped ? 'info' : 'done',
        title: 'Внешние инструменты проверены',
        detail: [
          typeof health.tools === 'number' ? `доступно: ${health.tools}` : null,
          health.skipped ? `недоступно: ${health.skipped}` : null,
        ].filter(Boolean).join(' · '),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Решение авто-оркестратора: ЧТО он включил и ПОЧЕМУ.
    // 🔴 Прежний роутер свой отказ не объяснял никак — молча отдавал «обычный ответ», и
    // понять, почему не случилось поиска, было нечем. Тот же урок уже выучен на плане.
    if (event.type === 'status_update' && event.metadata?.kind === 'auto_decision') {
      const auto = event.metadata.auto || {};
      const free = auto.source === 'shortcut';
      appendTraceEvent({
        kind: 'done',
        title: event.message || 'Режим выбран',
        detail: [autoModeReasonLabel(auto.reason_code), free ? 'Выбор режима — без вызова модели' : null].filter(Boolean).join(' · '),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Предложение дорогого режима — ШАГОМ ТРЕЙСА, а не карточкой под готовым ответом.
    // 🔴 Под ответом оно висело вечно: человек либо жал кнопку задним числом, либо она
    // просто мозолила глаза. В трейсе предложение оказывается там и тогда, когда решение
    // имеет смысл — по ходу работы, — и живёт ровно отведённый сервером срок.
    if (event.type === 'status_update' && event.metadata?.kind === 'mode_offer') {
      const offer = event.metadata.mode_offer || {};
      if (offer.blocking) awaitingDecisionRef.current = true;
      appendTraceEvent({
        kind: 'offer',
        title: event.message || `Предложен режим: ${offer.label || offer.mode}`,
        detail: autoModeReasonLabel(offer.reason_code),
        offer,
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Каталог workflow полностью внутренний. Показываем только безопасный факт выполнения:
    // без имени записи, точного запроса, результата или каких-либо параметров цепочки.
    if (event.type === 'status_update' && event.metadata?.kind === 'workflow_execution') {
      const execution = event.metadata.workflow_execution || {};
      appendTraceEvent({
        kind: 'done',
        title: event.message || 'Выполнен сохранённый сценарий',
        detail: execution.status === 'failed' ? 'Часть шагов завершилась с ошибкой' : '',
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Рассуждение модели, пришедшее ОТДЕЛЬНЫМ ПОЛЕМ провайдера (delta.reasoning /
    // reasoning_content), а не тегами <think> в теле ответа.
    // 🔴 Раньше читались только теги, поэтому все нынешние reasoning-модели показывали
    // пустую панель: они рассуждают, платим мы за это, а увидеть было нечего.
    if (event.type === 'status_update' && event.metadata?.kind === 'reasoning') {
      appendTraceEvent({
        kind: 'thinking',
        title: 'Размышления модели',
        detail: clampTraceDetail(event.message, 2000, true),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // План решения — ОТДЕЛЬНОЙ строкой с текстом плана, а не «Инструмент завершен».
    // 🔴 Жалоба: человек включил режим «Планирование», план строился и влиял на ответ, а
    // наружу уезжало одно число («План готов: 7 шагов»). Тумблер, чьё действие
    // ненаблюдаемо, неотличим от выключенного.
    if (event.type === 'tool_call_complete' && event.metadata?.plan) {
      appendTraceEvent({
        kind: 'plan',
        title: event.message || 'План решения',
        detail: String(event.metadata.plan),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Старые lifecycle-события продолжают идти для совместимых потребителей, но их
    // подробный аналог выше уже показан по status_update без дублей.
    if ((event.type === 'tool_call_start' || event.type === 'tool_call_complete') && event.metadata?.tool_progress) {
      return;
    }
    if (event.type === 'tool_call_complete') {
      appendTraceEvent({
        kind: 'done',
        title: `Завершён инструмент: ${getTraceName(event.tool_name)}`,
        detail: clampTraceDetail(event.result),
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    // Прогресс длительного/многошагового процесса → обновляем ОДИН прогресс-бар,
    // а не плодим строки статуса. Метаданные шлёт бэкенд (kind + progress + label):
    // research_progress (deep research) и multi_intent_progress (мульти-интент).
    if (
      event.type === 'status_update' &&
      (event.metadata?.kind === 'research_progress' || event.metadata?.kind === 'multi_intent_progress')
    ) {
      const pct = event.metadata.progress;
      updateTraceProgress?.(typeof pct === 'number' ? pct : null, event.metadata.label || event.message || '');
      return;
    }
    // Сборка контекста: видно, ЧЕМ занят контекст и что именно было сжато. Отдельной
    // строкой, а не generic-статусом, — это ответ на вопрос «почему кольцо такое».
    if (event.type === 'status_update' && event.metadata?.context) {
      const ctx = event.metadata.context;
      const compressed = Array.isArray(ctx.compressed) ? ctx.compressed : [];
      appendTraceEvent({
        kind: 'done',
        title: event.message || 'Контекст собран',
        detail: compressed.length
          ? `Крупные источники сжаты под бюджет окна: ${compressed.join(', ')}`
          : `Окно модели: ${ctx.window ?? '—'} токенов`,
        agent: event.agent_name,
        timestamp: event.timestamp,
      });
      return;
    }
    const mapping = {
      routing_start: { kind: 'info', title: 'Маршрутизатор анализирует запрос', detail: event.message || 'Подбор оптимального агента и модели' },
      // Мульти-интент: показываем отдельным заметным шагом (иначе тонет в generic
      // «Выбран агент: general»). Метаданные шлёт бэкенд: {multi_intent, steps}.
      routing_complete: event.metadata?.multi_intent
        ? { kind: 'done', title: `Мульти-интент: запрос разбит на ${event.metadata.steps ?? '?'} подзадач(и)`, detail: 'Подзадачи выполняются по очереди' }
        : { kind: 'done', title: `Выбран агент: ${getTraceName(event.agent_name, 'Автоматический выбор')}`, detail: event.message || '' },
      agent_start: { kind: 'done', title: `Запущен агент: ${getTraceName(event.agent_name, 'Помощник')}`, detail: event.message || 'Начата генерация ответа' },
      status_update: { kind: 'info', title: event.message || 'Обработка…', detail: '' },
      tool_call_start: { kind: 'info', title: `Запущен инструмент: ${getTraceName(event.tool_name)}`, detail: event.agent_name ? `Инициатор: ${getTraceName(event.agent_name, 'Помощник')}` : '' },
      structured_output: { kind: 'done', title: 'Подготовлен структурированный результат', detail: 'Данные готовы для отображения в UI' },
      error: { kind: 'error', title: 'Ошибка во время обработки', detail: event.error || 'Неизвестная ошибка' },
    };
    if (mapping[event.type]) appendTraceEvent({ ...mapping[event.type], agent: event.agent_name, timestamp: event.timestamp });
  }, [appendTraceEvent, updateTraceProgress, shouldIgnoreWsEvent, onContextCompacted, onWorkspaceInvalidated]);

  const wsCallbacks = useMemo(() => ({ onMessage: () => {}, onJobCreated, onComplete, onError, onDisconnect, onStreamChunk, onAgentReply, onAgentComplete, onAgentEvent }), [onAgentComplete, onAgentEvent, onAgentReply, onComplete, onDisconnect, onError, onJobCreated, onStreamChunk]);

  return { state: {}, actions: { wsCallbacks } };
}
