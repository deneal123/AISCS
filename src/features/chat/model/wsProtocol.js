import protocolManifest from './protocolManifest.json';

const FRAME_TYPES = new Set([
  ...protocolManifest.events,
  ...protocolManifest.websocket_frames,
]);
const ERROR_CODES = new Set(protocolManifest.error_codes);

const SAFE_ERROR_MESSAGES = Object.freeze({
  auth: 'Нет доступа к выбранному провайдеру.',
  cancelled: 'Выполнение отменено.',
  conflict: 'Данные изменились. Обновите состояние и повторите действие.',
  expired: 'Рабочая среда истекла.',
  invalid: 'Запрос не прошёл проверку.',
  no_compatible_model: 'Нет модели, совместимой с этим типом запроса.',
  payload: 'Провайдер отклонил формат запроса.',
  policy: 'Действие запрещено политикой выполнения.',
  protocol: 'Сервис вернул неподдерживаемый ответ.',
  provider_protocol: 'Провайдер вернул неподдерживаемый ответ.',
  quota: 'Лимит провайдера исчерпан.',
  rate_limit: 'Слишком много запросов. Повторите позже.',
  remote: 'Внешний сервис отклонил операцию.',
  safety: 'Запрос остановлен проверкой безопасности.',
  timeout: 'Истекло время ожидания ответа.',
  tls: 'Не удалось безопасно подключиться к провайдеру.',
  tls_config: 'Защищённое подключение к провайдеру не настроено.',
  tool_choice: 'Провайдер не поддержал требуемый режим инструмента.',
  tool_schema: 'Провайдер не поддержал схему инструмента.',
  transport: 'Сервис временно недоступен.',
  unavailable: 'Сервис временно недоступен.',
  internal: 'Выполнение завершилось с ошибкой.',
});

const SAFE_LEGACY_CODES = Object.freeze({
  insufficient_funds: 'Недостаточно средств на балансе.',
  unauthorized: 'Не удалось подтвердить доступ.',
  forbidden: 'Действие недоступно.',
  not_found: 'Запрошенные данные не найдены.',
});

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function validMetadata(value) {
  return value == null || isRecord(value);
}

function frameType(frame) {
  return nonEmptyString(frame?.type)
    ? frame.type
    : nonEmptyString(frame?.event) ? frame.event : '';
}

function validatePayload(frame, type) {
  if (!validMetadata(frame.metadata)) return false;
  switch (type) {
    case 'job_created':
      return nonEmptyString(frame.job_id)
        && (frame.celery_task_id == null || typeof frame.celery_task_id === 'string')
        && (frame.data == null || isRecord(frame.data));
    case 'stream_chunk':
      return typeof frame.data === 'string';
    case 'agent_reply':
      return typeof frame.reply === 'string';
    case 'agent_complete':
      return frame.message_id == null || typeof frame.message_id === 'string';
    case 'error':
      return true;
    case 'heartbeat':
      return true;
    default:
      return Number.isInteger(frame.seq) || frame.seq == null;
  }
}

export function validateWsFrame(value, depth = 0) {
  if (!isRecord(value)) return { ok: false, reason: 'invalid_record', eventType: '' };
  const type = frameType(value);
  if (!FRAME_TYPES.has(type)) {
    return { ok: false, reason: 'unknown_event', eventType: type };
  }
  if (type === 'replay' || type === 'claimed') {
    if (depth >= 1 || !isRecord(value.data)) {
      return { ok: false, reason: 'invalid_wrapper', eventType: type };
    }
    const nested = validateWsFrame(value.data, depth + 1);
    return nested.ok ? { ok: true, frame: value, eventType: type } : nested;
  }
  if (!validatePayload(value, type)) {
    return { ok: false, reason: 'invalid_payload', eventType: type };
  }
  return { ok: true, frame: value, eventType: type };
}

export function protocolError(eventType = '', reason = 'invalid_frame') {
  return {
    type: 'protocol_error',
    event_type: FRAME_TYPES.has(eventType) ? eventType : 'unknown',
    reason_code: ['invalid_record', 'unknown_event', 'invalid_wrapper', 'invalid_payload', 'invalid_json'].includes(reason)
      ? reason
      : 'invalid_frame',
  };
}

export function safeErrorMessage(frame) {
  const metadata = isRecord(frame?.metadata) ? frame.metadata : {};
  const rawCode = metadata.failure_code || frame?.error_code || frame?.code || 'internal';
  const code = typeof rawCode === 'string' ? rawCode : 'internal';
  if (ERROR_CODES.has(code)) return SAFE_ERROR_MESSAGES[code] || SAFE_ERROR_MESSAGES.internal;
  return SAFE_LEGACY_CODES[code] || SAFE_ERROR_MESSAGES.internal;
}

export { protocolManifest };
