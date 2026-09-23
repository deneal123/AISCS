const DEFAULT_FALLBACK_MESSAGE = 'Не удалось выполнить действие. Попробуйте ещё раз.';
const NETWORK_MESSAGE = 'Нет соединения с сервером. Проверьте интернет или повторите позже.';

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

const isLikelyErrorCode = (value) => typeof value === 'string' && /^[A-Z0-9_]+$/.test(value.trim());

const normalizeDetail = (detail) => {
  if (!detail && detail !== 0) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((item) => normalizeDetail(item?.msg || item?.message || item?.detail || item)).filter(Boolean).join('; ');
  if (typeof detail === 'object') {
    if (detail.message) return normalizeDetail(detail.message);
    if (detail.detail) return normalizeDetail(detail.detail);
    if (detail.msg) return normalizeDetail(detail.msg);
    const nested = Object.values(detail).map((value) => normalizeDetail(value)).filter(Boolean).join('; ');
    if (nested) return nested;
    return JSON.stringify(detail);
  }
  return String(detail);
};

export const mapIdentity = (data) => data;

export const mapApiError = (error, options = {}) => {
  const status = error?.response?.status ?? error?.status ?? null;
  const data = error?.response?.data ?? error?.details ?? null;
  const rawDetail = data?.detail ?? data?.message ?? data?.error ?? data ?? error?.message;
  // Код из ТЕЛА ответа приоритетнее axios-кода транспорта (ERR_BAD_REQUEST и т.п.):
  // иначе бэкендовый code (у нас — data.error.code) всегда затирается и сообщение
  // падает на общий STATUS_MESSAGES вместо понятного текста.
  const bodyCode =
    data?.code ??
    (rawDetail && typeof rawDetail === 'object' ? rawDetail.code : null) ??
    (typeof rawDetail === 'string' && isLikelyErrorCode(rawDetail) ? rawDetail.trim() : null);
  const code = options.kind === 'canceled' ? 'REQUEST_CANCELED' : (bodyCode ?? error?.code ?? null);

  const details = normalizeDetail(rawDetail) || null;
  const message = CODE_MESSAGES[code] || STATUS_MESSAGES[status] || (!status ? NETWORK_MESSAGE : (options.fallbackMessage || DEFAULT_FALLBACK_MESSAGE));

  return {
    type: 'DomainError',
    code: code || 'UNKNOWN_ERROR',
    message,
    details,
    status,
    isRetryable: !status || status >= 500 || status === 429,
    isCanceled: code === 'REQUEST_CANCELED',
    raw: error,
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
