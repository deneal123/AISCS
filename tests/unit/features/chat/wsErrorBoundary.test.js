import { act, renderHook } from '@testing-library/react';
import { safeErrorMessage } from '@features/chat/model/wsProtocol';
import { useChatStreamingLifecycle } from '@features/chat/hooks/orchestration/useChatStreamingLifecycle';

it.each(['constructor', '__proto__', 'toString', 'unrecognized'])('rejects unknown and inherited error codes: %s', (code) => {
  expect(safeErrorMessage({ code })).toBe('Выполнение завершилось с ошибкой.');
});

it.each([
  [{ message: 'PRIVATE_EXCEPTION_403_PERMISSION_BODY' }, 'Выполнение завершилось с ошибкой.'],
  [{ code: 'timeout', message: 'PRIVATE_EXCEPTION_BODY' }, 'Истекло время ожидания ответа.'],
  [{ code: 'insufficient_funds', message: 'PRIVATE_EXCEPTION_BODY' }, 'Недостаточно средств на балансе.'],
  [{ code: 'auth', message: 'PRIVATE_EXCEPTION_BODY' }, 'Нет доступа к выбранному провайдеру.'],
  [{ code: 'transport', message: 'PRIVATE_EXCEPTION_BODY' }, 'Сервис временно недоступен.'],
  [{ code: 'constructor', message: 'PRIVATE_EXCEPTION_BODY' }, 'Выполнение завершилось с ошибкой.'],
])('projects only bounded errors into trace and inline state', (error, message) => {
  const spies = {
    appendTraceEvent: jest.fn(), finalizeTraceSession: jest.fn(), setError: jest.fn(),
    clearCurrentJob: jest.fn(), setIsLoading: jest.fn(),
  };
  const { result } = renderHook(() => useChatStreamingLifecycle(spies));
  act(() => result.current.actions.wsCallbacks.onError(error));
  expect(spies.appendTraceEvent).toHaveBeenCalledWith({
    kind: 'error', title: 'Ошибка канала обработки', detail: message,
  });
  expect(spies.setError).toHaveBeenCalledWith(message);
  expect(spies.finalizeTraceSession).toHaveBeenCalledTimes(1);
  expect(spies.clearCurrentJob).toHaveBeenCalledTimes(1);
  expect(spies.setIsLoading).toHaveBeenCalledWith(false);
  expect(JSON.stringify(Object.values(spies).map((spy) => spy.mock.calls))).not.toContain('PRIVATE_EXCEPTION');
});

it('does not stringify unknown exception objects', () => {
  const spies = {
    appendTraceEvent: jest.fn(), finalizeTraceSession: jest.fn(), setError: jest.fn(),
    clearCurrentJob: jest.fn(), setIsLoading: jest.fn(),
  };
  const { result } = renderHook(() => useChatStreamingLifecycle(spies));
  const error = { message: { toString: () => { throw new Error('private serialization'); } } };
  expect(() => act(() => result.current.actions.wsCallbacks.onError(error))).not.toThrow();
  expect(spies.setError).toHaveBeenCalledWith('Выполнение завершилось с ошибкой.');
});
