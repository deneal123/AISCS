import { useEffect, useState } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { getDocumentBuild, publishDocumentArtifact } from '@api/chat';
import {
  useDocumentPublication, waitDocumentStatus,
} from '../../../../src/features/workspace-room/model/useDocumentPublication';

jest.mock('@api/chat', () => ({
  getDocumentBuild: jest.fn(), publishDocumentArtifact: jest.fn(),
}));

const makeBuild = (state) => ({
  build_id: 'build-1', state: 'visual_pending', final: true,
  artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }], publication_state: state,
});
const initialProps = { threadId: 'thread-1', active: true, initialBuild: makeBuild(null) };

describe('useDocumentPublication', () => {
  let notify;
  let refreshSnapshot;
  const renderPublication = (props = initialProps) => renderHook((input) => {
    const [build, setBuild] = useState(input.initialBuild);
    return {
      ...useDocumentPublication({ ...input, build, setBuild, notify, refreshSnapshot }),
      build,
    };
  }, { initialProps: props });

  beforeEach(() => {
    jest.resetAllMocks();
    notify = jest.fn();
    refreshSnapshot = jest.fn().mockResolvedValue(null);
    publishDocumentArtifact.mockResolvedValue({ publication_state: 'pending_delivery' });
    getDocumentBuild.mockResolvedValue(makeBuild('delivered'));
  });
  afterEach(() => { cleanup(); jest.useRealTimers(); });

  it('recovers an uncertain delivery read without repeating publication', async () => {
    getDocumentBuild.mockRejectedValueOnce(new Error('PRIVATE-RESPONSE'));
    const { result } = renderPublication();
    await act(async () => { await result.current.publish(); });
    await waitFor(() => expect(result.current.publicationError).toBe(true));
    expect(result.current.build.publication_state).toBe('pending_delivery');
    expect(result.current.publicationChecking).toBe(false);
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.publicationError).toBe(false);
    expect(result.current.build.publication_state).toBe('delivered');
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
    expect(getDocumentBuild).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(notify.mock.calls)).not.toContain('PRIVATE-RESPONSE');
  });

  it('does not turn a background project refresh into an automatic retry after read failure', async () => {
    getDocumentBuild.mockRejectedValueOnce(new Error('PRIVATE-READ'));
    const { result, rerender } = renderHook(({ snapshot }) => {
      const [build, setBuild] = useState(makeBuild(null));
      useEffect(() => { if (snapshot) setBuild(snapshot); }, [snapshot]);
      return useDocumentPublication({
        threadId: 'thread-1', build, setBuild, refreshSnapshot, notify,
      });
    }, { initialProps: { snapshot: null } });
    await act(async () => { await result.current.publish(); });
    await waitFor(() => expect(result.current.publicationError).toBe(true));
    const recovered = makeBuild(null);
    delete recovered.publication_state;
    rerender({ snapshot: recovered });
    await act(async () => { await Promise.resolve(); });
    expect(result.current.publicationError).toBe(true);
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
    await act(async () => { await result.current.checkPublication(); });
    expect(getDocumentBuild).toHaveBeenCalledTimes(2);
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
    expect(result.current.publicationError).toBe(false);
  });

  it('keeps a rejected POST uncertain until an authoritative read before retry', async () => {
    publishDocumentArtifact.mockRejectedValueOnce(new Error('PRIVATE-ACK'));
    getDocumentBuild.mockResolvedValueOnce(makeBuild(null));
    const { result } = renderPublication();
    const captured = result.current.publish;
    await act(async () => { await captured(); await captured(); });
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
    expect(result.current.publicationError).toBe(true);
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.publicationError).toBe(false);
    await act(async () => { await result.current.publish(); });
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(result.current.build.publication_state).toBe('delivered'));
  });

  it('preserves uncertain publication across an inactive Work surface', async () => {
    publishDocumentArtifact.mockRejectedValueOnce(new Error('PRIVATE-ACK'));
    const { result, rerender } = renderPublication();
    await act(async () => { await result.current.publish(); });
    rerender({ ...initialProps, active: false });
    rerender(initialProps);
    expect(result.current.publicationError).toBe(true);
    await act(async () => { await result.current.publish(); });
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.build.publication_state).toBe('delivered');
  });

  it.each(['pending_audit', 'pending_delivery'])('resumes only status reads for %s on reload', async (state) => {
    const { result } = renderPublication({ ...initialProps, initialBuild: makeBuild(state) });
    await waitFor(() => expect(result.current.build.publication_state).toBe('delivered'));
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
  });

  it('reconciles a Workspace-only final snapshot with the authoritative backend outbox', async () => {
    const recovered = makeBuild(null);
    delete recovered.publication_state;
    const { result } = renderPublication({ ...initialProps, initialBuild: recovered });
    await waitFor(() => expect(result.current.build.publication_state).toBe('delivered'));
    await act(async () => { await result.current.publish(); });
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
  });

  it('exposes recovered outbox unavailability inline, never as absent publication', async () => {
    const recovered = makeBuild(null);
    delete recovered.publication_state;
    getDocumentBuild.mockRejectedValueOnce(new Error('PRIVATE-OUTBOX'));
    const { result } = renderPublication({ ...initialProps, initialBuild: recovered });
    await waitFor(() => expect(result.current.publicationError).toBe(true));
    await act(async () => { await result.current.publish(); });
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.build.publication_state).toBe('delivered');
  });

  it('does not dispatch another POST after leaving during an uncertain acknowledgement', async () => {
    let resolve;
    publishDocumentArtifact.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const { result, rerender } = renderPublication();
    let pending;
    act(() => { pending = result.current.publish(); });
    await waitFor(() => expect(publishDocumentArtifact).toHaveBeenCalledTimes(1));
    rerender({ ...initialProps, active: false });
    await act(async () => { resolve({ publication_state: 'pending_delivery' }); await pending; });
    rerender(initialProps);
    expect(result.current.publicationError).toBe(true);
    await act(async () => { await result.current.publish(); });
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.build.publication_state).toBe('delivered');
  });

  it.each(['delivered', 'terminal'])('does not enqueue an already terminal %s publication', async (state) => {
    const { result } = renderPublication({ ...initialProps, initialBuild: makeBuild(state) });
    await act(async () => { await result.current.publish(); });
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
  });

  it('never announces a returned terminal state as queued or delivered', async () => {
    publishDocumentArtifact.mockResolvedValue({ publication_state: 'terminal' });
    const { result } = renderPublication();
    await act(async () => { await result.current.publish(); });
    expect(result.current.build.publication_state).toBe('terminal');
    expect(notify).not.toHaveBeenCalled();
    expect(getDocumentBuild).not.toHaveBeenCalled();
  });

  it('does not undo acknowledgement for failed snapshot or notification callbacks', async () => {
    refreshSnapshot.mockRejectedValue(new Error('PRIVATE-REFRESH'));
    notify.mockImplementation(() => { throw new Error('PRIVATE-NOTIFY'); });
    const { result } = renderPublication();
    await act(async () => { await result.current.publish(); });
    await waitFor(() => expect(result.current.build.publication_state).toBe('delivered'));
    expect(result.current.publicationError).toBe(false);
    expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
  });

  it.each(['foreign-build', 'foreign-artifact', 'missing-status', 'invalid-status'])(
    'rejects %s rather than claiming success', async (fault) => {
    const response = makeBuild('delivered');
    if (fault === 'foreign-build') response.build_id = 'another-build';
    else if (fault === 'foreign-artifact') response.artifacts[0].artifact_id = 'another-pdf';
    else if (fault === 'missing-status') delete response.publication_state;
    else response.publication_state = 'PRIVATE-STATUS';
    getDocumentBuild.mockResolvedValue(response);
    const { result } = renderPublication();
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.publicationError).toBe(true);
    expect(result.current.build).toEqual(makeBuild(null));
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    },
  );

  it.each(['thread', 'inactive', 'unmount'])('aborts status read and ignores late results after %s', async (change) => {
    let resolve;
    getDocumentBuild.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const { result, rerender, unmount } = renderPublication();
    let pending;
    act(() => { pending = result.current.checkPublication(); });
    await waitFor(() => expect(getDocumentBuild).toHaveBeenCalledTimes(1));
    const signal = getDocumentBuild.mock.calls[0][2].signal;
    if (change === 'thread') rerender({ ...initialProps, threadId: 'thread-2' });
    else if (change === 'inactive') rerender({ ...initialProps, active: false });
    else unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { resolve(makeBuild('delivered')); await pending; });
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    if (change !== 'unmount') expect(result.current.build.publication_state).toBeNull();
  });

  it('aborts the polling timer on unmount without another request or leaked listeners', async () => {
    jest.useFakeTimers();
    getDocumentBuild.mockResolvedValue(makeBuild('pending_delivery'));
    const { result, unmount } = renderPublication();
    let pending;
    await act(async () => { pending = result.current.checkPublication(); });
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
    expect(jest.getTimerCount()).toBe(2); // Poll pause and the independent deadline.
    unmount();
    await act(async () => { await pending; });
    expect(jest.getTimerCount()).toBe(0);
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
  });

  it('bounds monitoring and requires an explicit read retry after the window', async () => {
    jest.useFakeTimers();
    getDocumentBuild.mockResolvedValue(makeBuild('pending_delivery'));
    const { result } = renderPublication();
    let pending;
    await act(async () => { pending = result.current.checkPublication(); });
    for (let index = 0; index < 300; index += 1) {
      await act(async () => { jest.advanceTimersByTime(1000); });
    }
    await act(async () => { await pending; });
    expect(getDocumentBuild).toHaveBeenCalledTimes(300);
    expect(result.current.publicationError).toBe(true);
    expect(result.current.publicationChecking).toBe(false);
    expect(jest.getTimerCount()).toBe(0);
    getDocumentBuild.mockResolvedValue(makeBuild('delivered'));
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.build.publication_state).toBe('delivered');
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
  });

  it('ends observation at five minutes even while the current read is unresolved', async () => {
    jest.useFakeTimers();
    let resolve;
    getDocumentBuild.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const { result } = renderPublication();
    let pending;
    await act(async () => { pending = result.current.checkPublication(); });
    const signal = getDocumentBuild.mock.calls[0][2].signal;
    await act(async () => { jest.advanceTimersByTime(300_000); });
    expect(result.current.publicationChecking).toBe(false);
    expect(result.current.publicationError).toBe(true);
    expect(signal.aborted).toBe(true);
    expect(jest.getTimerCount()).toBe(0);
    // A transport that resolves after abort cannot update state or notify.
    await act(async () => { resolve(makeBuild('delivered')); await pending; });
    expect(result.current.build.publication_state).toBeNull();
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    await act(async () => { await result.current.checkPublication(); });
    expect(result.current.build.publication_state).toBe('delivered');
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
  });

  it('clamps each request timeout to the remaining observation budget', async () => {
    jest.useFakeTimers();
    let resolve;
    getDocumentBuild.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const { result } = renderPublication();
    let pending;
    await act(async () => { pending = result.current.checkPublication(); });
    expect(getDocumentBuild.mock.calls[0][2].timeout).toBe(30_000);
    await act(async () => {
      jest.advanceTimersByTime(290_000);
      resolve(makeBuild('pending_delivery'));
    });
    await act(async () => { jest.advanceTimersByTime(1000); });
    await act(async () => { await pending; });
    expect(getDocumentBuild.mock.calls[1][2].timeout).toBe(9000);
    expect(result.current.build.publication_state).toBe('delivered');
    expect(jest.getTimerCount()).toBe(0);
  });

  it('clips the last polling pause and does not issue a read after deadline', async () => {
    jest.useFakeTimers();
    let resolve;
    getDocumentBuild.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const { result } = renderPublication();
    let pending;
    await act(async () => { pending = result.current.checkPublication(); });
    await act(async () => {
      jest.advanceTimersByTime(299_500);
      resolve(makeBuild('pending_delivery'));
    });
    await act(async () => { jest.advanceTimersByTime(500); await pending; });
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
    expect(result.current.publicationChecking).toBe(false);
    expect(result.current.publicationError).toBe(true);
    expect(jest.getTimerCount()).toBe(0);
  });

  it('does not release a new retry owner when an expired read resolves late', async () => {
    jest.useFakeTimers();
    const requests = [];
    getDocumentBuild.mockImplementation(() => new Promise((resolve) => requests.push(resolve)));
    const { result } = renderPublication();
    let expired;
    await act(async () => { expired = result.current.checkPublication(); });
    await act(async () => { jest.advanceTimersByTime(300_000); });
    let current;
    await act(async () => { current = result.current.checkPublication(); });
    expect(requests).toHaveLength(2);
    expect(result.current.publicationChecking).toBe(true);
    await act(async () => { requests[0](makeBuild('delivered')); await expired; });
    expect(result.current.publicationChecking).toBe(true);
    expect(result.current.build.publication_state).toBeNull();
    expect(jest.getTimerCount()).toBe(1);
    expect(notify).not.toHaveBeenCalled();
    await act(async () => { requests[1](makeBuild('delivered')); await current; });
    expect(result.current.publicationChecking).toBe(false);
    expect(result.current.build.publication_state).toBe('delivered');
    expect(jest.getTimerCount()).toBe(0);
    expect(publishDocumentArtifact).not.toHaveBeenCalled();
  });

  it('ignores late publication acknowledgement after changing the thread', async () => {
    let resolve;
    publishDocumentArtifact.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const { result, rerender } = renderPublication();
    let pending;
    act(() => { pending = result.current.publish(); });
    await waitFor(() => expect(publishDocumentArtifact).toHaveBeenCalledTimes(1));
    rerender({ ...initialProps, threadId: 'thread-2' });
    await act(async () => { resolve({ publication_state: 'delivered' }); await pending; });
    expect(notify).not.toHaveBeenCalled();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(getDocumentBuild).not.toHaveBeenCalled();
    expect(result.current.build.publication_state).toBeNull();
    expect(result.current.publicationBusy).toBe(false);
  });
});

describe('waitDocumentStatus', () => {
  afterEach(() => jest.useRealTimers());
  it.each(['elapsed', 'aborted'])('removes abort listener after %s', async (ending) => {
    jest.useFakeTimers();
    const controller = new AbortController();
    const remove = jest.spyOn(controller.signal, 'removeEventListener');
    const pending = waitDocumentStatus(controller.signal);
    if (ending === 'aborted') controller.abort();
    else jest.advanceTimersByTime(1000);
    await pending;
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(jest.getTimerCount()).toBe(0);
  });
});
