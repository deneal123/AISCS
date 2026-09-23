import { renderHook } from '@testing-library/react';
import { useMemoryPanel } from '@features/chat/hooks/useMemoryPanel';

jest.mock('@api/chat', () => ({
  getUserMemory: jest.fn(),
  getUserMemoryDashboard: jest.fn(),
}));

const { getUserMemory, getUserMemoryDashboard } = require('@api/chat');

/**
 * Панель памяти: два запроса в РАЗНЫЕ хранилища (факты — Postgres, дашборд — MemOS).
 *
 * Замер: дашборд занимает 124-172 мс на каждое открытие, факты после прогрева — 3 мс.
 * Раньше дашборд уходил ТОЛЬКО после ответа по фактам, и задержки складывались: блок
 * семантической памяти появлялся заметно позже остальной панели.
 */
// ⚠️ Ждём МАКРОТАСКОМ, а не счётом `await Promise.resolve()`. Хук начинается с
// динамического `import('@api/chat')`, и число микротасков до нужной точки зависит от
// его внутренностей — тест на счётчике ломался бы от любой правки импорта.
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const setup = () => {
  const state = {
    memoryFacts: null,
    dashboard: undefined,
    count: null,
  };
  const { result } = renderHook(() =>
    useMemoryPanel({
      isAuthenticated: true,
      memoryDisclosure: { onOpen: jest.fn() },
      resolveSessionUserId: () => 'u-1',
      setMemoryFacts: (v) => { state.memoryFacts = v; },
      setMemoryDashboard: (v) => { state.dashboard = v; },
      setProfileMemoryCount: (v) => { state.count = v; },
      showAuthModal: jest.fn(),
      sideEffects: { notify: jest.fn() },
    })
  );
  return { open: result.current, state };
};

describe('useMemoryPanel', () => {
  beforeEach(() => jest.clearAllMocks());

  it('🔴 запускает оба запроса СРАЗУ, а не по очереди', async () => {
    const facts = deferred();
    getUserMemory.mockReturnValue(facts.promise);
    getUserMemoryDashboard.mockResolvedValue({ text: 3 });

    const { open } = setup();
    const done = open();
    await flush();

    // Ответа по фактам ещё нет — а дашборд уже запрошен. На последовательной загрузке
    // этот вызов случился бы только после resolve ниже.
    expect(getUserMemoryDashboard).toHaveBeenCalledTimes(1);

    facts.resolve({ facts: [] });
    await done;
  });

  it('🔴 рисует факты, не дожидаясь дашборда', async () => {
    const dash = deferred();
    getUserMemory.mockResolvedValue({ facts: [{ id: '1' }, { id: '2' }] });
    getUserMemoryDashboard.mockReturnValue(dash.promise);

    const { open, state } = setup();
    const done = open();
    await flush();

    // Дашборд ещё висит, а факты уже отрисованы: раньше они ждали его ответа.
    expect(state.memoryFacts).toHaveLength(2);
    expect(state.count).toBe(2);
    expect(state.dashboard).toBeUndefined();

    dash.resolve({ text: 1 });
    await done;
    expect(state.dashboard).toEqual({ text: 1 });
  });

  it('сбой дашборда не мешает показать факты', async () => {
    getUserMemory.mockResolvedValue({ facts: [{ id: '1' }] });
    getUserMemoryDashboard.mockRejectedValue(new Error('memos лежит'));

    const { open, state } = setup();
    await open();

    expect(state.memoryFacts).toHaveLength(1);
    expect(state.dashboard).toBeNull();
  });

  it('пустой дашборд скрывает виджет, а не показывает пустую рамку', async () => {
    getUserMemory.mockResolvedValue({ facts: [] });
    getUserMemoryDashboard.mockResolvedValue({});

    const { open, state } = setup();
    await open();

    expect(state.dashboard).toBeNull();
  });

  it('сбой по фактам уведомляет пользователя', async () => {
    getUserMemory.mockRejectedValue(new Error('нет сессии'));
    getUserMemoryDashboard.mockResolvedValue({ text: 1 });

    const notify = jest.fn();
    const { result } = renderHook(() =>
      useMemoryPanel({
        isAuthenticated: true,
        memoryDisclosure: { onOpen: jest.fn() },
        resolveSessionUserId: () => 'u-1',
        setMemoryFacts: jest.fn(),
        setMemoryDashboard: jest.fn(),
        setProfileMemoryCount: jest.fn(),
        showAuthModal: jest.fn(),
        sideEffects: { notify },
      })
    );
    await result.current();

    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ status: 'warning' }));
  });
});
