/**
 * Идентификатор нового чата обязан ОБНОВЛЯТЬСЯ.
 *
 * 🔴 Пока он был «один на монтирование», кнопка «новый чат» возвращала пользователя в тот
 * же тред: `/chat` немедленно редиректит на `/chat/<threadId>`, и второй раз подряд это был
 * тот же самый идентификатор. Снаружи это выглядело как перезагрузка страницы и повторный
 * вход в уже начатый чат.
 */
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useChatInitialization } from '@/features/chat/hooks/orchestration/useChatInitialization';

const wrapper = ({ children }) => (
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    {children}
  </MemoryRouter>
);

describe('useChatInitialization', () => {
  it('выдаёт НОВЫЙ идентификатор на каждый новый чат', () => {
    const { result } = renderHook(() => useChatInitialization(undefined), { wrapper });
    const first = result.current.state.threadId;

    let returned;
    act(() => {
      returned = result.current.actions.startFreshThread();
    });

    expect(returned).not.toBe(first);
    expect(result.current.state.threadId).toBe(returned);
  });

  it('не трогает идентификатор, заданный маршрутом', () => {
    const { result } = renderHook(() => useChatInitialization('route-thread'), { wrapper });
    expect(result.current.state.threadId).toBe('route-thread');
    act(() => {
      result.current.actions.startFreshThread();
    });
    expect(result.current.state.threadId).toBe('route-thread');
  });
});
