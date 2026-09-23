import { useCallback, useEffect, useRef } from 'react';
import { sendChatMessage } from '@api/chat';
import { extractUrlCandidates } from '@utils/urlParser';
import { clampTraceDetail } from '../../utils/trace';

/**
 * Оркестрация отправки сообщения: REST-fallback, выбор WS/REST транспорта,
 * авто-парсинг ссылок в тексте и трассировка шагов. Возвращает handleSendMessage.
 */
// 🔴 ПОТОЛОК НА ЧТЕНИЕ ССЫЛКИ. Своего дедлайна у разбора не было, и на неотвечающем
// источнике отправка ждала до упора: жалоба «минута фриза, потом сразу сообщение с
// ошибкой». Минута — это не медленно, это отсутствие границы. Здесь она есть, и человек
// получает ответ по тому, что успели прочитать.
export const URL_PARSE_TIMEOUT_MS = 12000;

export function normalizeAttachmentReferences(values) {
  return (Array.isArray(values) ? values : []).map((attachment) => ({
    filename: attachment?.filename || attachment?.name || '',
    file_type: attachment?.file_type || attachment?.kind || 'document',
    ...(attachment?.file_id ? { file_id: attachment.file_id } : {}),
    ...(attachment?.mime_type ? { mime_type: attachment.mime_type } : {}),
    ...(attachment?.digest || attachment?.content_sha256
      ? { content_sha256: attachment.digest || attachment.content_sha256 }
      : {}),
    ...(attachment?.extracted_text ? { extracted_text: attachment.extracted_text } : {}),
    ...(attachment?.file_url ? { file_url: attachment.file_url } : {}),
    ...(attachment?.is_tabular ? { is_tabular: true } : {}),
  })).filter((attachment) => attachment.filename || attachment.file_id);
}

export function withDeadline(promise, ms = URL_PARSE_TIMEOUT_MS) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_resolve, reject) => {
      timer = setTimeout(
        () => reject(new Error(`источник не ответил за ${Math.round(ms / 1000)} с`)),
        ms
      );
    }),
  ]).finally(() => clearTimeout(timer));
}

const _MODALITY_KIND = {
  image: 'image',
  audio: 'audio',
  code: 'code',
};

// 🔴 `data` НЕ выводится из расширения. `.json` носит и массив записей, и дерево
// настроек; кто из них таблица — решил backend по содержимому (`is_tabular`). Пока
// решало расширение, словарь ехал модальностью `data`, его текст выбрасывался из
// промпта «его посмотрит analyze_data», а SQL отвечал «десятой строки нет».
function _toModalityKind(attachment) {
  const known = _MODALITY_KIND[attachment?.file_type];
  if (known) return known;
  return attachment?.is_tabular ? 'data' : 'document';
}

export function useChatMessageSender({
  addMessage,
  appendTraceEvent,
  attachments,
  isFileUploading,
  clearError,
  clearAttachments,
  consumeUserDetached,
  composerRef,
  connectionState,
  deepResearchEnabled,
  ensureGuestLimit,
  finalizeTraceSession,
  forcedRoute,
  incrementRequests,
  initialFileContext,
  initialInputType,
  initialManualModel,
  isAuthenticated,
  resolveSessionUserId,
  selectedModelOverride,
  setError,
  setIsLoading,
  setSidebarSearch,
  showAuthModal,
  sideEffects,
  startTraceSession,
  threadId,
  upsertRecentThread,
  useWebSocket,
  voiceText,
  onVoiceConsumed,
  webSearchEnabled,
  multiIntentEnabled = false,
  planningEnabled = false,
  personaIds = [],
  memoryEnabled = true,
  ldrModel = '',
  ldrStrategy = '',
  wsSendMessage,
}) {
  // Отложенная отправка: если пользователь нажал «отправить», пока идёт захват
  // вложения (загрузка файла / запись/распознавание голоса), запоминаем намерение
  // здесь и авто-отправляем его по завершении захвата (эффект в конце хука).
  const pendingSendRef = useRef(null);

  const sendViaRest = useCallback(async (message, modelForRequest, inputTypeForRequest, options = {}) => {
    appendTraceEvent({
      kind: 'info',
      title: 'Используется HTTP fallback',
      detail: 'WebSocket недоступен, запрос отправлен через REST API',
    }, options.traceSessionId);

    if (!isAuthenticated) {
      incrementRequests();
    }

    if (!options.skipUserAppend) {
      const userMessage = {
        id: options.userMessageId || `user_${Date.now()}_${Math.random()}`,
        type: 'user',
        content: message,
        timestamp: new Date().toISOString(),
        ...((attachments || []).length
          ? { attachments: (attachments || []).map((a) => ({ filename: a.filename, file_type: a.file_type })) }
          : {}),
      };
      addMessage(userMessage);
    }

    const response = await sendChatMessage(
      threadId,
      message,
      resolveSessionUserId() || null,
      modelForRequest,
      inputTypeForRequest,
      options,
    );
    if (response?.reply) {
      const responseMeta = response?.metadata || {};
      const selectedModel = responseMeta?.selected_model || responseMeta?.model_routing?.selected_model || '';
      if (selectedModel) {
        appendTraceEvent({
          kind: 'done',
          title: `Выбрана модель: ${selectedModel}`,
          detail: responseMeta?.model_routing?.reason || '',
        }, options.traceSessionId);
      }

      if (responseMeta?.fallback_tool_path === 'web_search' || options.webSearch) {
        appendTraceEvent({
          kind: 'done',
          title: 'Вызван инструмент: Поиск в сети',
          detail: 'Собраны внешние источники и добавлены в контекст ответа',
        }, options.traceSessionId);
      }

      if (options.deepResearch) {
        appendTraceEvent({
          kind: 'done',
          title: 'Активирован режим Deep Research',
          detail: 'Использован углубленный сценарий исследования',
        }, options.traceSessionId);
      }

      if (options.fileContext) {
        appendTraceEvent({
          kind: 'done',
          title: 'Контекст из файла применен',
          detail: 'Фрагменты документа использованы при генерации ответа',
        }, options.traceSessionId);
      }

      appendTraceEvent({
        kind: responseMeta?.provider_unavailable ? 'error' : 'done',
        title: responseMeta?.provider_unavailable ? 'Ответ возвращен в деградированном режиме' : 'Ответ сгенерирован',
        detail: responseMeta?.provider_error || '',
      }, options.traceSessionId);

      const agentMessage = {
        id: `agent_${Date.now()}_${Math.random()}`,
        type: 'agent',
        content: response.reply,
        timestamp: new Date().toISOString(),
        metadata: response.metadata,
        file_url: response.file_url,
        complete: true,
        isTyping: false,
        typingProgress: 1,
      };
      addMessage(agentMessage);
      finalizeTraceSession(responseMeta?.provider_unavailable ? 'error' : 'done', options.traceSessionId);
    } else {
      appendTraceEvent({
        kind: 'error',
        title: 'Пустой ответ от REST API',
        detail: 'Ответ не содержит текста',
      }, options.traceSessionId);
      finalizeTraceSession('error', options.traceSessionId);
    }
    setIsLoading(false);
  }, [addMessage, appendTraceEvent, attachments, finalizeTraceSession, incrementRequests, isAuthenticated, resolveSessionUserId, setIsLoading, threadId]);

  const handleSendMessage = useCallback(async (message, sendOptions = {}) => {
    const skipUserAppend = !!sendOptions.skipUserAppend;
    const anchorMessageId = sendOptions.anchorMessageId || (!skipUserAppend ? `user_${Date.now()}_${Math.random()}` : null);
    const typed = typeof message === 'string' ? message.trim() : '';
    // Распознанное голосовое из превью (если есть) подмешиваем в сообщение:
    // голос идёт первым, затем — дописанный руками текст. Так голосовое уходит
    // обычным текстом (не вложением) и можно отправить его в одиночку.
    const voice = (voiceText || '').trim();
    const trimmed = voice ? (typed ? `${voice}\n\n${typed}` : voice) : typed;
    const confirmOfferId = String(sendOptions.confirmOfferId || '').trim();
    if (confirmOfferId && !trimmed) {
      if (!ensureGuestLimit()) return;
      const traceSessionId = startTraceSession('Подтверждённый запуск', anchorMessageId);
      setIsLoading(true);
      clearError();
      appendTraceEvent({
        kind: 'done',
        title: 'Подтверждено, запуск начат',
        detail: '',
      }, traceSessionId);
      try {
        if (useWebSocket || connectionState === 'connecting' || connectionState === 'connected') {
          wsSendMessage('', null, null, { confirmOfferId });
        } else {
          await sendViaRest('', null, null, {
            confirmOfferId,
            skipUserAppend: true,
            traceSessionId,
          });
        }
      } catch {
        setError('Не удалось подтвердить запуск. Обновите чат и попробуйте ещё раз.');
        appendTraceEvent({
          kind: 'error',
          title: 'Подтверждение не принято',
          detail: '',
        }, traceSessionId);
        finalizeTraceSession('error', traceSessionId);
        setIsLoading(false);
      }
      return;
    }
    if (!trimmed) {
      return;
    }

    // Вложение ещё готовится (загрузка файла / запись или распознавание голоса) →
    // не отправляем сейчас: иначе file_context уйдёт пустым (гонка — отправка до
    // того, как вложение попало в state). Но ЗАПОМИНАЕМ намерение (последнее
    // побеждает) и авто-отправим по завершении захвата — см. эффект ниже.
    if (isFileUploading) {
      pendingSendRef.current = { message, sendOptions };
      sideEffects.notify({
        title: 'Распознаю — отправлю после распознавания',
        status: 'info',
        duration: 2500,
      });
      return;
    }

    if (trimmed.length > 10000) {
      sideEffects.notify({
        title: 'Сообщение слишком длинное',
        description: 'Максимум 10000 символов.',
        status: 'warning',
        duration: 2500,
      });
      return;
    }

    composerRef.current?.clearInput();
    // Сообщение зафиксировано — убираем превью голосового (его текст уже в trimmed).
    onVoiceConsumed?.();
    setSidebarSearch('');

    // Разовый оверрайд модели (regenerate «на другой модели»): '' => Auto (null).
    const hasModelOverride = Object.prototype.hasOwnProperty.call(sendOptions, 'modelOverride');
    const modelForRequest = hasModelOverride
      ? (sendOptions.modelOverride || null)
      : (selectedModelOverride || initialManualModel || null);
    const activeAttachments = normalizeAttachmentReferences(
      sendOptions.attachmentRefs || attachments,
    );
    const messageAttachments = activeAttachments
      .map((att) => ({
        kind: _toModalityKind(att),
        name: att.filename || '',
        ...(att.file_id ? { file_id: att.file_id } : {}),
        ...(att.mime_type ? { mime_type: att.mime_type } : {}),
        ...(att.content_sha256 ? { digest: att.content_sha256 } : {}),
        content: att.extracted_text || '',
        // Ссылка на оригинал: описание картинки делается на АПЛОАДЕ, когда личность ещё
        // не выбрана, а некоторым специализациям нужно посмотреть на пиксели иначе.
        // Возим ссылку, не байты — тело сообщения и так несёт текст вложений.
        ...(att.file_url ? { source_url: att.file_url } : {}),
      }))
      .filter((att) => att.content.trim() || att.file_id);
    const primaryAttachment = activeAttachments[0] || null;
    // id всех приложенных файлов — сигнал бэкенду «новый файл в этом сообщении»
    // (не зависит от того, извлёкся ли текст).
    const fileIdsForRequest = activeAttachments.map((a) => a.file_id).filter(Boolean);
    // Открепил ли пользователь файл крестиком (сбрасывается здесь же, разово на отправку).
    const userDetachedFiles = consumeUserDetached?.() || false;
    const isMultimodal = messageAttachments.length >= 2;
    const attachedInputType = primaryAttachment?.file_type === 'audio'
      ? 'audio'
      : primaryAttachment?.file_type === 'image'
        ? 'image'
        : null;
    const inputTypeForRequest = attachedInputType || initialInputType || 'text';
    // Приоритет: явный форс-режим из UI (route_override). Иначе одиночное аудио ->
    // транскрипция; при >=2 модальностях бэкенд сам включает fan-out -> general.
    const audioRoute =
      !isMultimodal && primaryAttachment?.file_type === 'audio' ? 'audio_transcribe' : null;
    // Текстовое вложение не должно подменять намерение маршрутом `general`: backend
    // получает его как owned attachment и сам применяет policy. Иначе явный запрос
    // «напиши статью в PDF» никогда не доходил до `pdf_gen`.
    // 🔴 `sendOptions.routeOverride` — ВЫШЕ всего остального. Так приходит подтверждение
    // дорогого режима («запустить глубокое исследование»): человек нажал кнопку, и
    // подменять его выбор режимом из меню или служебным форсом по вложению нельзя.
    const routeOverrideForRequest = sendOptions.routeOverride || forcedRoute || audioRoute;

    if (!ensureGuestLimit()) {
      return;
    }

    setIsLoading(true);
    clearError();
    upsertRecentThread(threadId, trimmed);
    const traceSessionId = startTraceSession(trimmed, anchorMessageId);
    appendTraceEvent({
      kind: 'info',
      title: 'Запрос принят',
      // Сохраняем переносы строк запроса и даём чуть больше символов — трейс
      // покажет первые несколько строк/предложений (в 3 строки, дальше «…»).
      detail: clampTraceDetail(trimmed, 240, true),
    }, traceSessionId);

    if (webSearchEnabled) {
      appendTraceEvent({
        kind: 'info',
        title: 'Включен веб-поиск',
        detail: 'При необходимости будут вызваны внешние источники',
      }, traceSessionId);
    }

    if (deepResearchEnabled) {
      appendTraceEvent({
        kind: 'info',
        title: 'Включен режим Deep Research',
        detail: 'Маршрутизатор может выбрать исследовательский пайплайн',
      }, traceSessionId);
    }

    // 🔴 РЕПЛИКА ПОКАЗЫВАЕТСЯ ДО РАЗБОРА ССЫЛОК. Разбор — это сеть, и он стоял ПЕРЕД
    // показом: человек вставлял текст со ссылкой и на минуту получал замерший интерфейс,
    // в котором его сообщения не было вовсе. Ждать сеть, чтобы увидеть собственную
    // реплику, не должен никто; источники допишутся к ней, когда придут (`ADD_MESSAGE`
    // с тем же id заменяет сообщение на месте).
    const buildUserMessage = (sources) => ({
      id: anchorMessageId,
      type: 'user',
      content: trimmed,
      timestamp: new Date().toISOString(),
      ...(activeAttachments.length
        ? { attachments: activeAttachments.map((a) => ({
          filename: a.filename,
          file_type: a.file_type,
          ...(a.file_id ? { file_id: a.file_id } : {}),
          ...(a.mime_type ? { mime_type: a.mime_type } : {}),
          ...(a.content_sha256 ? { digest: a.content_sha256 } : {}),
        })) }
        : {}),
      ...(sources?.length ? { metadata: { sources } } : {}),
    });
    const showsUserMessage =
      !skipUserAppend
      && (useWebSocket || connectionState === 'connecting' || connectionState === 'connected');
    if (showsUserMessage) {
      addMessage(buildUserMessage(null));
    }

    // Auto-parse URLs found in the message text
    let urlContext = (!isMultimodal ? primaryAttachment?.extracted_text : '') || initialFileContext || '';
    let parsedSources = [];
    try {
      const foundUrls = extractUrlCandidates(trimmed, 2);
      if (foundUrls.length > 0) {
        sideEffects.notify({ title: foundUrls.length > 1 ? 'Читаю ссылки…' : 'Читаю ссылку…', status: 'info', duration: 2000, isClosable: true });
        const { parseUrl: apiParseUrl } = await import('@api/chat');
        const results = await Promise.allSettled(foundUrls.map((u) => withDeadline(apiParseUrl(u))));
        const parsedBlocks = [];
        results.forEach((r, i) => {
          const url = foundUrls[i];
          const ok = r.status === 'fulfilled' && !!r.value?.content;
          parsedSources.push({ url, title: ok ? (r.value.title || url) : url, ok });
          if (ok) {
            const title = r.value.title || url;
            parsedBlocks.push(`## Страница: ${title}\nURL: ${url}\n\n${String(r.value.content).slice(0, 8000)}`);
          } else {
            const err = r.status === 'rejected' ? (r.reason?.message || 'недоступно') : (r.value?.error || 'пустой ответ');
            parsedBlocks.push(`## Страница: ${url}\n[не удалось прочитать: ${err}]`);
          }
        });
        const parsed = parsedBlocks.length ? `# __URL_CONTEXT__\n${parsedBlocks.join('\n\n---\n\n')}` : '';
        const okCount = results.filter((r) => r.status === 'fulfilled' && r.value?.content).length;
        if (parsed) {
          urlContext = urlContext ? `${urlContext}\n\n${parsed}` : parsed;
          appendTraceEvent({
            kind: okCount > 0 ? 'done' : 'error',
            title: okCount > 0 ? 'Ссылки проанализированы' : 'Ссылки недоступны',
            detail: `Обработано URL: ${okCount}/${foundUrls.length} (${foundUrls.join(', ')})`,
          }, traceSessionId);
          if (okCount > 0) {
            sideEffects.notify({ title: okCount > 1 ? 'Ссылки прочитаны' : 'Ссылка прочитана', status: 'success', duration: 2000 });
          } else {
            sideEffects.notify({ title: 'Не удалось прочитать ссылку', status: 'warning', duration: 2500 });
          }
        }
      }
    } catch (err) {
      appendTraceEvent({
        kind: 'error',
        title: 'Ошибка парсинга ссылки',
        detail: err?.message || String(err),
      }, traceSessionId);
    }

    try {
      if (useWebSocket || connectionState === 'connecting' || connectionState === 'connected') {
        // Реплика уже показана выше; здесь она лишь дополняется источниками, если разбор
        // ссылок что-то дал. Замена по id, а не второе сообщение.
        if (showsUserMessage && parsedSources.length) {
          addMessage(buildUserMessage(parsedSources));
        }
        const wsOptions = {
          ...(webSearchEnabled && { webSearch: true }),
          ...(deepResearchEnabled && { deepResearch: true }),
          ...(multiIntentEnabled && { multiIntent: true }),
          // Шлём ТОЛЬКО когда включено: отсутствие поля означает «авто по
          // сложности», и это не то же самое, что явное `false` («никогда»).
          ...(planningEnabled && { planning: true }),
          ...(personaIds?.length && { personaIds }),
          // Память включена по умолчанию — на бэкенд шлём флаг ТОЛЬКО когда выключена.
          // Память шлём только когда ВЫКЛючена (по умолчанию — включена).
          ...(memoryEnabled === false && { memoryEnabled: false }),
          ...(ldrModel && { ldrModel }),
          ...(ldrStrategy && { ldrStrategy }),
          // Без обрезки: бэкенд ограничивает текст вложения на аплоаде, а под окно
          // модели его ужимает map-reduce компрессор — ему нужен документ целиком.
          // Прежний substring(0, 6000) отдавал модели лишь начало файла.
          ...(urlContext && { fileContext: urlContext }),
          ...(routeOverrideForRequest && { routeOverride: routeOverrideForRequest }),
          ...(messageAttachments.length && { attachments: messageAttachments }),
          // Сигнал «в этом сообщении приложен файл» — даже если текст извлечь не
          // удалось: иначе воркер подставит ПРЕЖНИЙ файл треда и агент ответит про него.
          ...(fileIdsForRequest.length && { fileIds: fileIdsForRequest }),
          // Пользователь открепил файл и шлёт без него → стереть thread-память файла,
          // иначе follow-up воскресит прежний («открепил, а он в контексте»).
          ...(userDetachedFiles && !messageAttachments.length && { detachFiles: true }),
          // 🔴 СОГЛАСИЕ НА ДОРОГОЕ — ОТДЕЛЬНЫМ ПРИЗНАКОМ, а не значением routeOverride.
          // Просмотр видео это ИНСТРУМЕНТ: он не меняет, кто отвечает, он снимает запор с
          // признака контекста. Втиснув его в перечень маршрутов, мы отправили бы имя,
          // которого среди них нет, и бэкенд отверг бы запрос схемой.
          ...(sendOptions.watchVideo && { watchVideo: true }),
          ...(sendOptions.confirmExpensiveRun && { confirmExpensiveRun: true }),
        };
        wsSendMessage(trimmed, modelForRequest, inputTypeForRequest, wsOptions);
        clearAttachments();
      } else {
        await sendViaRest(trimmed, modelForRequest, inputTypeForRequest, {
          webSearch: webSearchEnabled,
          deepResearch: deepResearchEnabled,
          fileContext: urlContext || '',
          routeOverride: routeOverrideForRequest,
          confirmExpensiveRun: !!sendOptions.confirmExpensiveRun,
          attachments: messageAttachments,
          skipUserAppend,
          userMessageId: anchorMessageId,
          traceSessionId,
        });
        clearAttachments();
      }
    } catch (sendError) {
      if (sendError?.status === 429) {
        showAuthModal(
          'Превышен лимит запросов',
          'Бесплатные запросы закончились. Войдите, чтобы продолжить.',
          'request_limit'
        );
      } else {
        setError('Не удалось отправить сообщение. Попробуйте еще раз.');
      }
      appendTraceEvent({
        kind: 'error',
        title: 'Отправка не удалась',
        detail: sendError?.message || 'Неизвестная ошибка отправки',
      }, traceSessionId);
      finalizeTraceSession('error', traceSessionId);
      setIsLoading(false);
    }
  }, [addMessage, appendTraceEvent, attachments, isFileUploading, clearError, clearAttachments, composerRef, connectionState, deepResearchEnabled, ensureGuestLimit, finalizeTraceSession, forcedRoute, initialFileContext, initialInputType, initialManualModel, selectedModelOverride, sendViaRest, setError, setIsLoading, setSidebarSearch, showAuthModal, startTraceSession, threadId, sideEffects, upsertRecentThread, useWebSocket, voiceText, onVoiceConsumed, consumeUserDetached, webSearchEnabled, multiIntentEnabled, planningEnabled, personaIds, memoryEnabled, ldrModel, ldrStrategy, wsSendMessage]);

  // Авто-отправка отложенного сообщения: как только захват вложения завершился
  // (isFileUploading true→false) и есть запомненное намерение — отправляем его
  // ровно один раз. Ref очищается ДО вызова → повторный прогон эффекта не
  // приведёт к двойной отправке. К этому моменту вложение уже в attachments
  // (addAttachment вызывается раньше сброса флага), поэтому уйдёт с контекстом.
  const prevBusyRef = useRef(isFileUploading);
  useEffect(() => {
    const wasBusy = prevBusyRef.current;
    prevBusyRef.current = isFileUploading;
    if (wasBusy && !isFileUploading && pendingSendRef.current) {
      const { message, sendOptions } = pendingSendRef.current;
      pendingSendRef.current = null;
      // Отправляем ТЕКУЩИЙ текст композера: в него мог дописаться транскрипт
      // голосового уже после того, как отправка была отложена (голос → композер).
      // Фолбэк — запомненное сообщение.
      const current = composerRef.current?.getInputValue?.();
      handleSendMessage(current && current.trim() ? current : message, sendOptions);
    }
  }, [isFileUploading, handleSendMessage, composerRef]);

  return { handleSendMessage };
}
