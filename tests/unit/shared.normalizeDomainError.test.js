import { normalizeDomainError } from '../../src/shared/lib/error';

describe('normalizeDomainError', () => {
  it.each(['ide_git_not_empty', 'ide_git_conflict', 'ide_generation_changed'])('keeps the closed IDE detail code %s instead of the Axios transport code', code => {
    const mapped = normalizeDomainError({ code: 'ERR_BAD_REQUEST', response: { status: 409, data: { detail: code } } });
    expect(mapped.code).toBe(code);
    expect(normalizeDomainError(mapped).code).toBe(code);
    expect(mapped.message).not.toContain(code);
  });
  it('normalizes network error', () => {
    const error = { message: 'Network Error', code: 'ERR_NETWORK' };

    expect(normalizeDomainError(error)).toMatchObject({
      status: null,
      code: 'ERR_NETWORK',
      message: 'Нет соединения с сервером. Проверьте интернет или повторите позже.',
      details: 'Network Error',
    });
  });

  it('normalizes unauthorized and forbidden errors', () => {
    const unauthorized = { response: { status: 401, data: { detail: 'token expired' } } };
    const forbidden = { response: { status: 403, data: { detail: 'forbidden' } } };

    expect(normalizeDomainError(unauthorized)).toMatchObject({
      status: 401,
      message: 'Сессия истекла или доступ запрещён. Авторизуйтесь снова.',
      details: 'token expired',
    });

    expect(normalizeDomainError(forbidden)).toMatchObject({
      status: 403,
      message: 'Доступ ограничен или исчерпан лимит. Обратитесь к администратору или повторите позже.',
      details: 'forbidden',
    });
  });

  it('normalizes 5xx errors', () => {
    const serverError = { response: { status: 500, data: { detail: 'internal' } } };

    expect(normalizeDomainError(serverError)).toMatchObject({
      status: 500,
      message: 'На сервере произошла ошибка. Попробуйте позже.',
      details: 'internal',
    });
  });

  it('handles unknown error with fallback message', () => {
    const unknown = { response: { status: 418, data: { detail: { foo: 'bar' } } } };

    expect(normalizeDomainError(unknown, { fallbackMessage: 'Что-то пошло не так' })).toMatchObject({
      status: 418,
      message: 'Что-то пошло не так',
      details: 'bar',
    });
  });

  it.each(['constructor', '__proto__', 'toString'])('never uses inherited dictionary values for %s', (code) => {
    const normalized = normalizeDomainError({ response: { status: 400, data: { code } } });
    expect(typeof normalized.message).toBe('string');
    expect(normalized.message).toBe('Некорректные данные. Проверьте введённую информацию и попробуйте снова.');
  });

  it('does not coerce a malformed code into a dictionary key', () => {
    const code = { toString: () => { throw new Error('PRIVATE_CODE_SERIALIZATION'); } };
    expect(() => normalizeDomainError({ response: { status: 503, data: { code } } })).not.toThrow();
  });

  it('preserves the accepted code when normalizing a DomainError again', () => {
    const first = normalizeDomainError({ response: { status: 400, data: {
      code: 'invalid_code', detail: 'PRIVATE_RESPONSE_BODY',
    } } });
    const second = normalizeDomainError(first);
    expect(second.code).toBe('invalid_code');
    expect(second.message).toBe(first.message);
    expect(second.details).toBe(first.details);
    expect(second.raw).toBe(first.raw);
  });

  it('handles circular and non-serializable private details without breaking feedback', () => {
    const detail = { message: null };
    detail.message = detail;
    expect(() => normalizeDomainError({ response: { status: 500, data: { detail } } })).not.toThrow();
    const unknown = { message: () => 'PRIVATE_FUNCTION_BODY' };
    expect(normalizeDomainError({ response: { status: 500, data: { detail: unknown } } }).details).toBeNull();
  });

  it('bounds diagnostic detail size and does not guess network failure for an unknown exception', () => {
    const result = normalizeDomainError({ response: { status: 500, data: { detail: 'x'.repeat(10000) } } });
    expect(result.details.length).toBeLessThanOrEqual(2048);
    expect(normalizeDomainError(new Error('PRIVATE_INTERNAL'), { fallbackMessage: 'Не удалось сохранить.' }).message).toBe('Не удалось сохранить.');
  });

  it('does not invent diagnostic details on repeated normalization or mark cancellation retryable', () => {
    const first = normalizeDomainError({ response: { status: 500 } });
    expect(normalizeDomainError(first).details).toBeNull();
    expect(normalizeDomainError({}, { kind: 'canceled' })).toMatchObject({
      code: 'REQUEST_CANCELED', message: 'Запрос отменён.', isRetryable: false,
    });
  });
});
