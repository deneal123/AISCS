import { act, renderHook, waitFor } from '@testing-library/react';
import { acquireWorkspaceLease, releaseWorkspaceLease, renewWorkspaceLease } from '@api/chat';
import { useWorkspaceLease } from '@features/workspace-room/model/useWorkspaceLease';

jest.mock('@api/chat', () => ({
  acquireWorkspaceLease: jest.fn(),
  releaseWorkspaceLease: jest.fn(),
  renewWorkspaceLease: jest.fn(),
}));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

describe('workspace lease request ownership', () => {
  let notify;

  beforeEach(() => {
    jest.resetAllMocks();
    jest.useFakeTimers();
    acquireWorkspaceLease.mockResolvedValue({ fence: 7 });
    releaseWorkspaceLease.mockResolvedValue(undefined);
    renewWorkspaceLease.mockResolvedValue({ fence: 7 });
    notify = jest.fn();
  });
  afterEach(() => jest.useRealTimers());

  function renderLease() {
    return renderHook(({ threadId, active }) => useWorkspaceLease({ threadId, active, notify }), {
      initialProps: { threadId: 'thread-1', active: true },
    });
  }

  it('releases a pending acquire completed after Work becomes inactive', async () => {
    const pending = deferred();
    acquireWorkspaceLease.mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderLease();
    let acquiring;
    act(() => { acquiring = result.current.acquire('notes.md'); });
    await waitFor(() => expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1));
    rerender({ threadId: 'thread-1', active: false });
    await act(async () => { pending.resolve({ fence: 11 }); await acquiring; });
    expect(result.current.lease.fence).toBe(0);
    expect(releaseWorkspaceLease).toHaveBeenCalledWith('thread-1', 'notes.md', 11, expect.any(Object));
  });

  it('does not dispatch an obsolete acquire after awaiting the previous release', async () => {
    const releasing = deferred();
    const { result } = renderLease();
    await act(async () => result.current.acquire('first.md'));
    releaseWorkspaceLease.mockReturnValueOnce(releasing.promise);
    let obsolete;
    act(() => { obsolete = result.current.acquire('obsolete.md'); });
    await waitFor(() => expect(releaseWorkspaceLease).toHaveBeenCalledTimes(1));
    acquireWorkspaceLease.mockResolvedValueOnce({ fence: 12 });
    await act(async () => result.current.acquire('current.md'));
    await act(async () => { releasing.resolve(); await obsolete; });
    expect(acquireWorkspaceLease.mock.calls.map((call) => call[1])).toEqual(['first.md', 'current.md']);
    expect(result.current.lease).toEqual(expect.objectContaining({ path: 'current.md', fence: 12 }));
  });

  it.each(['success', 'failure'])('ignores an old renew %s after same-path reacquisition', async (outcome) => {
    const renewal = deferred();
    renewWorkspaceLease.mockReturnValueOnce(renewal.promise);
    const { result } = renderLease();
    await act(async () => result.current.acquire('notes.md'));
    await act(async () => jest.advanceTimersByTime(20_000));
    expect(renewWorkspaceLease).toHaveBeenCalledTimes(1);
    acquireWorkspaceLease.mockResolvedValueOnce({ fence: 12 });
    await act(async () => result.current.reacquire());
    await act(async () => {
      if (outcome === 'success') renewal.resolve({ fence: 7 });
      else renewal.reject({ status: 423 });
    });
    expect(result.current.lease).toEqual(expect.objectContaining({ fence: 12, status: 'editing' }));
    expect(notify).not.toHaveBeenCalled();
  });

  it('does not revive a released lease from a late renewal', async () => {
    const renewal = deferred();
    renewWorkspaceLease.mockReturnValueOnce(renewal.promise);
    const { result } = renderLease();
    await act(async () => result.current.acquire('notes.md'));
    await act(async () => jest.advanceTimersByTime(20_000));
    await act(async () => result.current.release());
    await act(async () => renewal.resolve({ fence: 7 }));
    expect(result.current.lease.fence).toBe(0);
    expect(result.current.lease.status).toBe('released');
  });

  it('does not overlap renewal requests for one lease', async () => {
    const renewal = deferred();
    renewWorkspaceLease.mockReturnValueOnce(renewal.promise);
    const { result } = renderLease();
    await act(async () => result.current.acquire('notes.md'));
    await act(async () => jest.advanceTimersByTime(60_000));
    expect(renewWorkspaceLease).toHaveBeenCalledTimes(1);
    await act(async () => renewal.resolve({ fence: 7 }));
  });

  it('continues renewing after a confirmed current renewal', async () => {
    const { result } = renderLease();
    await act(async () => result.current.acquire('notes.md'));
    await act(async () => jest.advanceTimersByTime(20_000));
    await act(async () => jest.advanceTimersByTime(20_000));
    expect(renewWorkspaceLease).toHaveBeenCalledTimes(2);
    expect(result.current.lease.status).toBe('editing');
  });

  it('reports only a current renewal failure as lost', async () => {
    renewWorkspaceLease.mockRejectedValueOnce({ status: 423 });
    const { result } = renderLease();
    await act(async () => result.current.acquire('notes.md'));
    await act(async () => jest.advanceTimersByTime(20_000));
    expect(result.current.lease).toEqual(expect.objectContaining({ fence: 0, status: 'lost' }));
    expect(notify).toHaveBeenCalledTimes(1);
  });

  it('does not dispatch a captured old-thread acquire into the new lifecycle', async () => {
    const { result, rerender } = renderLease();
    const oldAcquire = result.current.acquire;
    rerender({ threadId: 'thread-2', active: true });
    await act(async () => oldAcquire('notes.md'));
    expect(acquireWorkspaceLease).not.toHaveBeenCalled();
    expect(result.current.lease.path).toBe('');
  });
});
