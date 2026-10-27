import { act, renderHook } from '@testing-library/react';
import { useChatMemoryActions } from '../../../src/features/chat/hooks/orchestration/useChatMemoryActions';
import { addMemoryFact, getUserMemory } from '@api/chat';

jest.mock('@api/chat', () => ({ addMemoryFact: jest.fn(), getUserMemory: jest.fn() }));
beforeEach(() => jest.clearAllMocks());

function setup() {
  const notify = jest.fn();
  return { notify, ...renderHook(() => useChatMemoryActions({
    resolveSessionUserId: () => 'synthetic-user', setMemoryFacts: jest.fn(),
    setMemoryDashboard: jest.fn(), setProfileMemoryCount: jest.fn(), notify,
  })) };
}

it('ошибка сохранения возвращает отказ, чтобы форма сохранила черновик', async () => {
  addMemoryFact.mockRejectedValueOnce(new Error('private'));
  const { result } = setup();
  await act(async () => expect(result.current.addMemoryFact('Факт')).resolves.toBe(false));
  expect(getUserMemory).not.toHaveBeenCalled();
});

it('ошибка чтения после подтверждённой записи не предлагает записать факт повторно', async () => {
  addMemoryFact.mockResolvedValueOnce({ fact: { id: 'saved' } });
  getUserMemory.mockRejectedValueOnce(new Error('private'));
  const { result, notify } = setup();
  await act(async () => expect(result.current.addMemoryFact('Факт')).resolves.toBe(true));
  expect(addMemoryFact).toHaveBeenCalledTimes(1);
  expect(notify).toHaveBeenCalledWith(expect.objectContaining({ title: 'Факт сохранён, но список не обновлён' }));
});
