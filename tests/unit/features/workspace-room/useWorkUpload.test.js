import { act, renderHook, waitFor } from '@testing-library/react';
import { uploadFileToWorkspace, uploadFileToLibrary } from '@api/chat';
import { useWorkUpload } from '../../../../src/features/workspace-room/model/useWorkUpload';

jest.mock('@api/chat', () => ({
  uploadFileToWorkspace: jest.fn(),
  uploadFileToLibrary: jest.fn(),
}));

describe('useWorkUpload', () => {
  beforeEach(() => jest.clearAllMocks());

  const file = () => new File(['body'], 'brief.txt');
  const options = { uploadIntentId: '00000000-0000-4000-8000-000000000001' };

  it('uploads only to Library without calling workspace activation or transcription', async () => {
    uploadFileToLibrary.mockResolvedValue({ outcome: 'library_uploaded', file: { file_id: 'saved' } });
    const notify = jest.fn(); const refreshSnapshot = jest.fn();
    const { result } = renderHook(() => useWorkUpload({ threadId: 'a', notify, refreshSnapshot }));
    await act(async () => result.current.upload(file(), { ...options, libraryOnly: true }));
    expect(uploadFileToLibrary).toHaveBeenCalledTimes(1);
    expect(uploadFileToWorkspace).not.toHaveBeenCalled();
    expect(result.current.lastResult).toMatchObject({ ok: true, outcome: 'library_uploaded' });
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ status: 'success', title: 'Файл сохранён в библиотеке' }));
  });
  const deferred = () => {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
  };

  it('rejects a retained old-thread upload without aborting the current upload', async () => {
    const request = deferred();
    uploadFileToWorkspace.mockReturnValue(request.promise);
    const notify = jest.fn();
    const refreshSnapshot = jest.fn();
    const { result, rerender } = renderHook(
      ({ threadId }) => useWorkUpload({ threadId, notify, refreshSnapshot }),
      { initialProps: { threadId: 'a' } },
    );
    const oldUpload = result.current.upload;
    rerender({ threadId: 'b' });
    let pending;
    act(() => { pending = result.current.upload(file(), options); });
    await waitFor(() => expect(uploadFileToWorkspace).toHaveBeenCalledTimes(1));
    const currentSignal = uploadFileToWorkspace.mock.calls[0].at(-1).signal;
    let staleOutcome;
    await act(async () => { staleOutcome = await oldUpload(file(), options); });
    expect(staleOutcome).toMatchObject({ ok: false, cancelled: true });
    expect(currentSignal.aborted).toBe(false);
    expect(result.current.busy).toBe(true);
    expect(uploadFileToWorkspace).toHaveBeenCalledTimes(1);
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    await act(async () => { request.resolve({ outcome: 'imported' }); await pending; });
    expect(result.current.lastResult).toMatchObject({ ok: true, outcome: 'imported' });
  });

  it('rejects a retained upload after unmount before dispatch or reconciliation', async () => {
    uploadFileToWorkspace.mockResolvedValue({ outcome: 'imported' });
    const notify = jest.fn();
    const refreshSnapshot = jest.fn();
    const { result, unmount } = renderHook(
      () => useWorkUpload({ threadId: 'a', notify, refreshSnapshot }),
    );
    const upload = result.current.upload;
    unmount();
    let outcome;
    await act(async () => { outcome = await upload(file(), options); });
    expect(outcome).toMatchObject({ ok: false, cancelled: true });
    expect(uploadFileToWorkspace).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
  });

  it('does not submit a request whose caller already cancelled', async () => {
    const controller = new AbortController();
    controller.abort();
    const notify = jest.fn();
    const refreshSnapshot = jest.fn();
    const { result } = renderHook(() => useWorkUpload({ threadId: 'a', notify, refreshSnapshot }));
    let outcome;
    await act(async () => {
      outcome = await result.current.upload(file(), { ...options, signal: controller.signal });
    });
    expect(outcome).toMatchObject({ ok: false, cancelled: true });
    expect(uploadFileToWorkspace).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
    expect(result.current.busy).toBe(false);
  });

  it('reconciles cancellation even when a late committed response resolves', async () => {
    const request = deferred();
    uploadFileToWorkspace.mockReturnValue(request.promise);
    const controller = new AbortController();
    const notify = jest.fn();
    const refreshSnapshot = jest.fn();
    const { result } = renderHook(() => useWorkUpload({ threadId: 'a', notify, refreshSnapshot }));
    let pending;
    act(() => {
      pending = result.current.upload(file(), { ...options, signal: controller.signal });
    });
    await waitFor(() => expect(uploadFileToWorkspace).toHaveBeenCalledTimes(1));
    let outcome;
    await act(async () => {
      controller.abort();
      request.resolve({ outcome: 'imported', revision: 'r1' });
      outcome = await pending;
    });
    expect(outcome).toMatchObject({ ok: false, cancelled: true });
    expect(refreshSnapshot).toHaveBeenCalledTimes(1);
    expect(notify).not.toHaveBeenCalled();
    expect(result.current.lastResult).toMatchObject({ cancelled: true });
  });

  it('ignores stale error feedback after thread changes during reconciliation', async () => {
    uploadFileToWorkspace.mockRejectedValue({ status: 503 });
    const refresh = deferred();
    const refreshSnapshot = jest.fn(() => refresh.promise);
    const notify = jest.fn();
    const { result, rerender } = renderHook(
      ({ threadId }) => useWorkUpload({ threadId, notify, refreshSnapshot }),
      { initialProps: { threadId: 'a' } },
    );
    let pending;
    act(() => { pending = result.current.upload(file(), options); });
    await waitFor(() => expect(refreshSnapshot).toHaveBeenCalledTimes(1));
    rerender({ threadId: 'b' });
    await act(async () => { refresh.resolve(); await pending; });
    expect(notify).not.toHaveBeenCalled();
    expect(result.current.lastResult).toBeNull();
    expect(result.current.busy).toBe(false);
  });

  it('keeps confirmed upload success when an independent snapshot refresh fails', async () => {
    uploadFileToWorkspace.mockResolvedValue({ outcome: 'imported', revision: 'r1' });
    const refreshSnapshot = jest.fn().mockRejectedValue(new Error('private-refresh-marker'));
    const notify = jest.fn();
    const { result } = renderHook(() => useWorkUpload({ threadId: 'a', notify, refreshSnapshot }));
    let outcome;
    await act(async () => { outcome = await result.current.upload(file(), options); });
    expect(outcome).toMatchObject({ ok: true, outcome: 'imported' });
    expect(result.current.lastResult).toMatchObject({ ok: true });
    expect(refreshSnapshot).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(notify.mock.calls)).not.toContain('private-refresh-marker');
  });

  it('does not forward progress from a superseded thread', async () => {
    const request = deferred();
    uploadFileToWorkspace.mockReturnValue(request.promise);
    const onProgress = jest.fn();
    const { result, rerender } = renderHook(
      ({ threadId }) => useWorkUpload({ threadId }),
      { initialProps: { threadId: 'a' } },
    );
    let pending;
    act(() => { pending = result.current.upload(file(), { ...options, onProgress }); });
    await waitFor(() => expect(uploadFileToWorkspace).toHaveBeenCalledTimes(1));
    const progress = uploadFileToWorkspace.mock.calls[0][4];
    rerender({ threadId: 'b' });
    await act(async () => { progress(75); request.resolve({ outcome: 'imported' }); await pending; });
    expect(onProgress).not.toHaveBeenCalled();
  });

  it('cancels the owned request when the selected thread changes', async () => {
    let observedSignal;
    uploadFileToWorkspace.mockImplementation((...args) => {
      const options = args.at(-1);
      observedSignal = options.signal;
      return new Promise((_resolve, reject) => {
        observedSignal.addEventListener('abort', () => {
          const error = new Error('cancelled');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      });
    });
    const refreshSnapshot = jest.fn();
    const notify = jest.fn();
    const { result, rerender } = renderHook(
      ({ threadId }) => useWorkUpload({ threadId, refreshSnapshot, notify }),
      { initialProps: { threadId: 'thread-a' } },
    );

    let pending;
    act(() => {
      pending = result.current.upload(new File(['body'], 'brief.txt'), {
        uploadIntentId: '00000000-0000-4000-8000-000000000001',
      });
    });
    await waitFor(() => expect(observedSignal).toBeDefined());

    rerender({ threadId: 'thread-b' });
    expect(observedSignal.aborted).toBe(true);
    await expect(pending).resolves.toEqual({ ok: false, cancelled: true, status: 0 });
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });
});
