import { act, renderHook, waitFor } from '@testing-library/react';
import { getChatProviderStatus } from '@shared/api/chat';
import { useProviderStatus } from '@features/chat/hooks/useProviderStatus';

jest.mock('@shared/api/chat', () => ({ getChatProviderStatus: jest.fn() }));

afterEach(() => { jest.useRealTimers(); jest.clearAllMocks(); });

it('keeps cached rows explicitly stale after a failed background read and aborts on unmount', async () => {
  jest.useFakeTimers();
  const data = { state: 'available', ready: 1, total: 1, providers: [] };
  getChatProviderStatus.mockResolvedValueOnce(data).mockRejectedValueOnce(new Error('private'));
  const { result, unmount } = renderHook(useProviderStatus);
  await waitFor(() => expect(result.current.data).toEqual(data));
  await act(async () => { jest.advanceTimersByTime(30000); });
  expect(result.current).toEqual({ data, stale: true });
  const signal = getChatProviderStatus.mock.calls[1][0].signal;
  unmount();
  expect(signal.aborted).toBe(true);
  expect(getChatProviderStatus).toHaveBeenCalledTimes(2);
});

it('retires a pending request without admitting another operation', () => {
  getChatProviderStatus.mockReturnValue(new Promise(() => {}));
  const { unmount } = renderHook(useProviderStatus);
  const signal = getChatProviderStatus.mock.calls[0][0].signal;
  unmount();
  expect(signal.aborted).toBe(true);
  expect(getChatProviderStatus).toHaveBeenCalledTimes(1);
});

it('does not erase previous evidence when the backend returns an unknown empty snapshot', async () => {
  jest.useFakeTimers();
  const data = { state: 'available', ready: 1, total: 1, providers: [{ id: 'gigachat' }] };
  getChatProviderStatus.mockResolvedValueOnce(data)
    .mockResolvedValueOnce({ state: 'unknown', ready: 0, total: 0, providers: [] });
  const { result, unmount } = renderHook(useProviderStatus);
  await waitFor(() => expect(result.current.data).toEqual(data));
  await act(async () => { jest.advanceTimersByTime(30000); });
  expect(result.current).toEqual({ data, stale: true });
  unmount();
});
