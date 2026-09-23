/**
 * Успех обязан побеждать ранее записанную ошибку.
 *
 * 🔴 Живой прогон: обрыв канала помечал сессию провалившейся, ответ приходил резервным
 * путём, и над полным готовым ответом висело «Не удалось подготовить ответ».
 */
import { renderHook, act } from '@testing-library/react';
import { useTraceSessions } from '@/features/chat/hooks/useTraceSessions';

const startAndFinish = (result, statuses) => {
  act(() => { result.current.startTraceSession('msg-1'); });
  statuses.forEach((s) => act(() => { result.current.finalizeTraceSession(s); }));
  return result.current.traceSessions[0];
};

describe('статус сессии трейса', () => {
  it('ответ отменяет ранее записанную ошибку канала', () => {
    const { result } = renderHook(() => useTraceSessions({ showTracePanel: true }));
    expect(startAndFinish(result, ['error', 'done']).status).toBe('done');
  });

  it('порядок не важен: успех остаётся успехом', () => {
    const { result } = renderHook(() => useTraceSessions({ showTracePanel: true }));
    expect(startAndFinish(result, ['done', 'error']).status).toBe('done');
  });

  it('без успеха ошибка остаётся ошибкой', () => {
    const { result } = renderHook(() => useTraceSessions({ showTracePanel: true }));
    expect(startAndFinish(result, ['error']).status).toBe('error');
  });
});

describe('ошибка одного шага', () => {
  it('не завершает сессию и не уводит остальной ход в новую карточку', () => {
    const { result } = renderHook(() => useTraceSessions({ showTracePanel: true }));
    act(() => { result.current.startTraceSession('msg-1'); });
    act(() => { result.current.appendTraceEvent({ kind: 'error', title: 'Ссылки недоступны' }); });
    act(() => { result.current.appendTraceEvent({ kind: 'info', title: 'Запущен агент' }); });

    expect(result.current.traceSessions).toHaveLength(1);
    const titles = result.current.traceSessions[0].events.map((e) => e.title);
    expect(titles).toEqual(['Ссылки недоступны', 'Запущен агент']);
    expect(result.current.traceSessions[0].status).toBe('running');
  });
});

describe('подтверждение дорогого запуска', () => {
  it('переводит последнюю ожидающую карточку в accepted только после server ack', () => {
    const { result } = renderHook(() => useTraceSessions({ showTracePanel: true }));
    act(() => { result.current.startTraceSession('msg-1'); });
    act(() => {
      result.current.appendTraceEvent({
        kind: 'offer',
        title: 'Нужно подтверждение стоимости',
        offer: { mode: 'expensive_run', status: 'pending', expired: false },
      });
    });
    act(() => { result.current.markConfirmationAccepted(); });

    expect(result.current.traceSessions[0].events[0].offer).toEqual({
      mode: 'expensive_run',
      status: 'accepted',
      expired: false,
    });
  });
});
