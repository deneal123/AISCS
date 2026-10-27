import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { downloadDocumentArtifact } from '@api/chat';
import { useDocumentPreview } from '../../../../src/features/workspace-room/model/useDocumentPreview';

jest.mock('@api/chat', () => ({ downloadDocumentArtifact: jest.fn() }));

const makeBuild = (id = 'build-1') => ({
  build_id: id,
  artifacts: [{ role: 'pdf', artifact_id: `${id}-pdf` }],
});
const initialProps = { threadId: 'thread-1', build: makeBuild(), active: true };
const renderPreview = () => renderHook((props) => useDocumentPreview(props), { initialProps });

describe('useDocumentPreview', () => {
  let createUrl;
  let revokeUrl;

  beforeEach(() => {
    jest.clearAllMocks();
    createUrl = URL.createObjectURL;
    revokeUrl = URL.revokeObjectURL;
    URL.createObjectURL = jest.fn()
      .mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second');
    URL.revokeObjectURL = jest.fn();
    downloadDocumentArtifact.mockResolvedValue(new Blob(['pdf']));
  });

  afterEach(() => {
    cleanup();
    URL.createObjectURL = createUrl;
    URL.revokeObjectURL = revokeUrl;
  });

  it('revokes each allocated URL exactly once on replacement and unmount', async () => {
    const { result, unmount } = renderPreview();
    await act(async () => { await result.current.openPreview(); });
    expect(result.current.previewUrl).toBe('blob:first');
    await act(async () => { await result.current.openPreview(); });
    expect(result.current.previewUrl).toBe('blob:second');
    expect(URL.revokeObjectURL.mock.calls).toEqual([['blob:first']]);
    unmount();
    expect(URL.revokeObjectURL.mock.calls).toEqual([['blob:first'], ['blob:second']]);
  });

  it('clears the old preview on build change and rejects captured old action', async () => {
    const { result, rerender } = renderPreview();
    const oldAction = result.current.openPreview;
    await act(async () => { await oldAction(); });
    rerender({ ...initialProps, build: makeBuild('build-2') });
    expect(result.current.previewUrl).toBe('');
    await act(async () => { await oldAction(); });
    expect(downloadDocumentArtifact).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:first');
  });

  it('aborts a superseded download, ignores its response and preserves new busy ownership', async () => {
    const requests = [];
    downloadDocumentArtifact.mockImplementation((...args) => new Promise((resolve) => {
      requests.push({ args, resolve });
    }));
    const { result, rerender } = renderPreview();
    let oldPending;
    act(() => { oldPending = result.current.openPreview(); });
    await waitFor(() => expect(requests).toHaveLength(1));
    rerender({ ...initialProps, build: makeBuild('build-2') });
    expect(requests[0].args[3].signal.aborted).toBe(true);
    let newPending;
    act(() => { newPending = result.current.openPreview(); });
    await waitFor(() => expect(requests).toHaveLength(2));
    await act(async () => { requests[0].resolve(new Blob(['old'])); await oldPending; });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(result.current.previewBusy).toBe(true);
    await act(async () => { requests[1].resolve(new Blob(['new'])); await newPending; });
    expect(result.current.previewBusy).toBe(false);
    expect(result.current.previewUrl).toBe('blob:first');
  });

  it('retains an existing preview on read failure and allows explicit retry', async () => {
    const { result } = renderPreview();
    await act(async () => { await result.current.openPreview(); });
    downloadDocumentArtifact.mockRejectedValueOnce(new Error('private-response-body'));
    await act(async () => { await result.current.openPreview(); });
    expect(result.current.previewUrl).toBe('blob:first');
    expect(result.current.previewError).toBe(true);
    expect(result.current.previewBusy).toBe(false);
    await act(async () => { await result.current.openPreview(); });
    expect(result.current.previewError).toBe(false);
    expect(result.current.previewUrl).toBe('blob:second');
  });

  it('rejects an action captured while the Work surface is inactive', async () => {
    const { result, rerender } = renderPreview();
    const oldAction = result.current.openPreview;
    rerender({ ...initialProps, active: false });
    await act(async () => { await oldAction(); });
    expect(downloadDocumentArtifact).not.toHaveBeenCalled();
  });
});
