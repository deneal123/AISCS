const DEFAULT_FALLBACK_MESSAGE = 'Не удалось выполнить действие. Попробуйте ещё раз.';
const NETWORK_MESSAGE = 'Нет соединения с сервером. Проверьте интернет или повторите позже.';
const NETWORK_CODES = new Set(['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT']);
const DETAIL_LIMIT = 2048;

const STATUS_MESSAGES = {
  400: 'Некорректные данные. Проверьте введённую информацию и попробуйте снова.',
  401: 'Сессия истекла или доступ запрещён. Авторизуйтесь снова.',
  403: 'Доступ ограничен или исчерпан лимит. Обратитесь к администратору или повторите позже.',
  404: 'Запрашиваемые данные не найдены.',
  409: 'Конфликт данных. Обновите страницу и повторите попытку.',
  413: 'Файл слишком большой. Уменьшите размер и загрузите его снова.',
  415: 'Неподдерживаемый формат файла.',
  429: 'Слишком много запросов. Подождите немного и повторите.',
  500: 'На сервере произошла ошибка. Попробуйте позже.',
  502: 'Сервис недоступен. Повторите попытку чуть позже.',
  503: 'Сервис временно недоступен. Попробуйте позже.',
};

const CODE_MESSAGES = {
  DATASET_REMOVED: 'Файл уже удалён. Обновите список датасетов, чтобы увидеть актуальное состояние.',
  JOB_LIMIT_REACHED: 'Лимит запусков исчерпан. Подождите перед новой попыткой или обратитесь к администратору.',
  FILE_TOO_LARGE: STATUS_MESSAGES[413],
  REQUEST_CANCELED: 'Запрос отменён.',
  // Аутентификация — понятные сообщения вместо общего «Некорректные данные».
  email_already_exists: 'Пользователь с таким email уже зарегистрирован. Войдите в аккаунт или используйте другой email.',
  weak_password: 'Пароль не подходит: минимум 8 символов, хотя бы одна буква и одна цифра.',
  invalid_credentials: 'Неверный email или пароль. Проверьте данные и попробуйте снова.',
  // Подтверждение email кодом (регистрация + OTP при входе).
  invalid_code: 'Неверный код. Проверьте цифры из письма и попробуйте снова.',
  code_expired: 'Срок действия кода истёк. Запросите новый код.',
  too_many_attempts: 'Слишком много попыток. Запросите новый код и попробуйте позже.',
  code_resend_too_soon: 'Новый код можно запросить чуть позже. Подождите немного.',
  email_not_verified: 'Подтвердите email: мы отправили код на вашу почту.',
  verification_unavailable: 'Подтверждение по email временно недоступно. Попробуйте позже.',
  account_blocked: 'Аккаунт заблокирован. Обратитесь к администратору.',
  // 422 от Pydantic (напр. слишком короткий пароль/битый email) — понятнее общего фолбэка.
  validation_error: 'Проверьте правильность заполнения полей и попробуйте снова.',
};

const isLikelyErrorCode = (value) => typeof value === 'string'
  && /^(?:[A-Z0-9_]+|ide_[a-z0-9_]+)$/.test(value.trim());

const normalizeDetail = (detail, state = { seen: new WeakSet(), nodes: 128 }, depth = 0) => {
  if (state.nodes-- <= 0 || depth > 6 || detail == null) return '';
  if (typeof detail === 'string') return detail.slice(0, DETAIL_LIMIT);
  if (typeof detail === 'boolean' || (typeof detail === 'number' && Number.isFinite(detail))) return String(detail);
  if (typeof detail !== 'object' || state.seen.has(detail)) return '';
  state.seen.add(detail);
  try {
    const descriptors = Object.getOwnPropertyDescriptors(detail);
    const preferred = ['message', 'detail', 'msg'].map((key) => descriptors[key]?.value)
      .find((value) => value != null && value !== '');
    if (preferred != null) return normalizeDetail(preferred, state, depth + 1);
    const values = Array.isArray(detail) ? detail.slice(0, 32)
      : Object.values(descriptors).filter((item) => Object.hasOwn(item, 'value')).slice(0, 32).map((item) => item.value);
    let result = '';
    for (const value of values) {
      if (state.nodes <= 0 || result.length >= DETAIL_LIMIT) break;
      const text = normalizeDetail(value, state, depth + 1);
      if (text) result += `${result ? '; ' : ''}${text}`;
    }
    return result.slice(0, DETAIL_LIMIT);
  } catch {
    return '';
  }
};

export const mapIdentity = (data) => data;

export const mapApiError = (error, options = {}) => {
  const mapped = error?.type === 'DomainError';
  const statusValue = error?.response?.status ?? error?.status;
  const status = Number.isInteger(statusValue) && statusValue >= 100 && statusValue <= 599 ? statusValue : null;
  const data = error?.response?.data ?? error?.details ?? null;
  const rawDetail = mapped ? error?.details : data?.detail ?? data?.message ?? data?.error ?? data ?? error?.message;
  // Код из ТЕЛА ответа приоритетнее axios-кода транспорта (ERR_BAD_REQUEST и т.п.):
  // иначе бэкендовый code (у нас — data.error.code) всегда затирается и сообщение
  // падает на общий STATUS_MESSAGES вместо понятного текста.
  const bodyCode = mapped ? null : (
    data?.code ??
    (rawDetail && typeof rawDetail === 'object' ? rawDetail.code : null) ??
    (typeof rawDetail === 'string' && isLikelyErrorCode(rawDetail) ? rawDetail.trim() : null));
  const codeValue = options.kind === 'canceled' ? 'REQUEST_CANCELED' : (bodyCode ?? error?.code ?? null);
  const code = typeof codeValue === 'string' && /^[A-Za-z0-9_]{1,128}$/.test(codeValue) ? codeValue : null;

  const details = normalizeDetail(rawDetail) || null;
  const fallback = typeof options.fallbackMessage === 'string' && options.fallbackMessage ? options.fallbackMessage : DEFAULT_FALLBACK_MESSAGE;
  const message = (Object.hasOwn(CODE_MESSAGES, code) ? CODE_MESSAGES[code] : null)
    || (Object.hasOwn(STATUS_MESSAGES, status) ? STATUS_MESSAGES[status] : null)
    || (!status && NETWORK_CODES.has(code) ? NETWORK_MESSAGE : fallback);

  return {
    type: 'DomainError',
    code: code || 'UNKNOWN_ERROR',
    message,
    details,
    status,
    isRetryable: code !== 'REQUEST_CANCELED' && (!status || status >= 500 || status === 429),
    isCanceled: code === 'REQUEST_CANCELED',
    raw: mapped ? error.raw ?? null : error,
  };
};

export const mapChatUploadResponse = (data = {}) => {
  if (!data.file_id) {
    const error = new Error('Файл не был сохранён в библиотеке');
    error.code = 'FILE_PERSISTENCE_FAILED';
    error.status = 503;
    throw error;
  }
  const extractedText = data.extracted_text || '';
  return {
    ...data,
    file_id: data.file_id,
    download_url: data.download_url || data.file_url || null,
    file_context: extractedText,
    content_preview: extractedText,
  };
};

export const mapModelsResponse = (data = {}) => data?.models || [];
export const mapProfileDto = (data = {}) => ({ ...data });
export const mapJobDto = (data = {}) => ({ ...data });
