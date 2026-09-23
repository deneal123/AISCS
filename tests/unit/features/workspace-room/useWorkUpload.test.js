import { act, renderHook, waitFor } from '@testing-library/react';
import { uploadFileToWorkspace } from '@api/chat';
import { useWorkUpload } from '../../../../src/features/workspace-room/model/useWorkUpload';

jest.mock('@api/chat', () => ({
  uploadFileToWorkspace: jest.fn(),
}));

describe('useWorkUpload', () => {
  beforeEach(() => jest.clearAllMocks());

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
