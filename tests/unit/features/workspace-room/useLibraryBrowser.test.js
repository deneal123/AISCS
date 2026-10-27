import { act, renderHook, waitFor } from '@testing-library/react';
import { getAccountWorkLibrary } from '@api/chat';
import { useLibraryBrowser } from '../../../../src/features/workspace-room/model/useLibraryBrowser';

jest.mock('@api/chat', () => ({ getAccountWorkLibrary: jest.fn() }));
const page = (name, more = false) => ({ state: 'ready', items: [{ file_id: name, name }], next_offset: more ? 10 : null });
beforeEach(() => { jest.clearAllMocks(); getAccountWorkLibrary.mockResolvedValue(page('first', true)); });

it('загружает отдельные страницы и не накапливает файлы', async () => {
  const { result } = renderHook(() => useLibraryBrowser({ enabled: true }));
  await waitFor(() => expect(result.current.items[0]?.name).toBe('first'));
  getAccountWorkLibrary.mockResolvedValueOnce(page('second'));
  act(() => result.current.goToPage(1));
  await waitFor(() => expect(result.current.items[0]?.name).toBe('second'));
  expect(result.current.items).toHaveLength(1);
  expect(getAccountWorkLibrary).toHaveBeenLastCalledWith(expect.objectContaining({ params: { limit: 10, offset: 10, q: '' } }));
  act(() => result.current.search('отчёт'));
  await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenLastCalledWith(expect.objectContaining({ params: { limit: 10, offset: 0, q: 'отчёт' } })));
});

it('сохраняет последнюю подтверждённую страницу при ошибке и повторяет только чтение', async () => {
  const { result } = renderHook(() => useLibraryBrowser({ enabled: true }));
  await waitFor(() => expect(result.current.items).toHaveLength(1));
  getAccountWorkLibrary.mockRejectedValueOnce(new Error('private'));
  act(() => result.current.goToPage(1));
  await waitFor(() => expect(result.current.error).toBe(true));
  expect(result.current.page).toBe(0);
  expect(result.current.items[0].name).toBe('first');
  getAccountWorkLibrary.mockResolvedValueOnce(page('second'));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.page).toBe(1));
});

it('отменяет старый запрос и игнорирует его поздний результат', async () => {
  let resolveOld;
  getAccountWorkLibrary.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const { result, unmount } = renderHook(() => useLibraryBrowser({ enabled: true }));
  await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1));
  const signal = getAccountWorkLibrary.mock.calls[0][0].signal;
  act(() => result.current.search('новый'));
  expect(signal.aborted).toBe(true);
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => resolveOld(page('stale')));
  expect(result.current.items[0].name).toBe('first');
  unmount();
  expect(getAccountWorkLibrary.mock.calls[1][0].signal.aborted).toBe(true);
});

it('не читает закрытую библиотеку и не отправляет незавершённый IME-запрос', async () => {
  const { result, rerender } = renderHook(({ enabled }) => useLibraryBrowser({ enabled }), { initialProps: { enabled: false } });
  expect(getAccountWorkLibrary).not.toHaveBeenCalled();
  act(() => { result.current.setComposing(true); result.current.search('файл'); });
  rerender({ enabled: true });
  expect(getAccountWorkLibrary).not.toHaveBeenCalled();
  act(() => result.current.setComposing(false));
  await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1));
});
