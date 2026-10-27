import { act, renderHook } from '@testing-library/react';
import { useChatContextCompaction } from '../../../src/features/chat/hooks/orchestration/useChatContextCompaction';

function setup(send = jest.fn(() => true)) {
  const notify = jest.fn();
  const hook = renderHook(() => useChatContextCompaction({
    messages: [], isLoading: false, notify, sendControlRef: { current: send },
  }));
  return { ...hook, notify, send };
}

beforeEach(() => jest.useFakeTimers());
afterEach(() => { jest.clearAllTimers(); jest.useRealTimers(); });

it('быстрые повторные клики отправляют одну команду', () => {
  const { result, send } = setup();
  act(() => { result.current.compact(); result.current.compact(); });
  expect(send).toHaveBeenCalledTimes(1);
  expect(result.current.compacting).toBe(true);
});

it.each([true, false])('результат заменяет уведомление начала: %s', (ok) => {
  const { result, notify } = setup();
  act(() => result.current.compact());
  act(() => result.current.onCompacted({ reason: 'empty', summary: 'Резюме' }, ok));
  expect(notify.mock.calls.map(([options]) => options.operationId))
    .toEqual(['context-compaction', 'context-compaction']);
  expect(notify.mock.calls[0][0].duration).toBe(20000);
  expect(notify.mock.calls[1][0].title).toBe(ok ? 'Контекст сжат' : 'Сжимать нечего');
  expect(result.current.compacting).toBe(false);
  act(() => jest.advanceTimersByTime(16000));
  expect(notify).toHaveBeenCalledTimes(2);
});

it.each(['error', 'no_summary', 'no_thread_or_user', undefined])(
  'не выдаёт ошибку сервиса за короткий диалог: %s', (reason) => {
    const { result, notify } = setup();
    act(() => result.current.onCompacted({ reason }, false));
    expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({
      title: 'Контекст не сжат', status: 'warning',
    }));
  },
);

it('при потере ответа завершает индикацию честным неизвестным результатом', () => {
  const { result, notify, send } = setup();
  act(() => result.current.compact());
  act(() => jest.advanceTimersByTime(15000));
  expect(result.current.compacting).toBe(false);
  expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({
    title: 'Результат сжатия пока неизвестен', operationId: 'context-compaction',
  }));
  expect(send).toHaveBeenCalledTimes(1);
});

it('сообщает об отсутствии соединения без зависшего состояния', () => {
  const { result, notify } = setup(jest.fn(() => false));
  act(() => result.current.compact());
  expect(result.current.compacting).toBe(false);
  expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ title: 'Сжатие не запущено' }));
});
