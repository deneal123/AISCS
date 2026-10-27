import { act, renderHook, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { usePdfPreparation } from '@features/workspace-room/model/usePdfPreparation';
import { useWorkActionOwner } from '@features/workspace-room/model/useWorkActionOwner';
import { preparePdfWorkspace } from '@api/chat';

jest.mock('@api/chat', () => ({ preparePdfWorkspace: jest.fn() }));
const prepared = () => ({ state: 'ready', project_path: 'documents/default', workspace: {
  state: 'ready', revision: 'r2', entries: [{ path: 'documents/default/document.toml', type: 'file' }],
} });
const props = (extra = {}) => ({ threadId: 'thread', active: true, snapshot: {
  hub: { loading: false, workspace: { state: 'absent', entries: [] }, room: {}, library: { items: [] } },
  applySnapshot: jest.fn(),
}, begin: jest.fn(() => ({ threadId: 'thread' })), owns: jest.fn(() => true), finish: jest.fn(), ...extra });
beforeEach(() => { jest.resetAllMocks(); preparePdfWorkspace.mockResolvedValue(prepared()); });

it('StrictMode cannot strand preparation behind a retired action owner or dispatch twice', async () => {
  const value = props();
  const view = renderHook(() => {
    const owner = useWorkActionOwner({ threadId: value.threadId, active: true });
    return usePdfPreparation({ ...value, ...owner, actionBusy: owner.busy });
  }, { wrapper: StrictMode });
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  expect(preparePdfWorkspace).toHaveBeenCalledTimes(1);
  expect(value.snapshot.applySnapshot).toHaveBeenCalledTimes(1);
});

it('prepares once after truthful discovery, without a manual creation state', async () => {
  const value = props(); value.snapshot.hub.loading = true;
  const view = renderHook(usePdfPreparation, { initialProps: value });
  expect(preparePdfWorkspace).not.toHaveBeenCalled();
  value.snapshot.hub.loading = false;
  view.rerender({ ...value });
  expect(view.result.current.status).toBe('preparing');
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  expect(preparePdfWorkspace).toHaveBeenCalledTimes(1);
  expect(value.snapshot.applySnapshot).toHaveBeenCalledWith(expect.objectContaining({
    workspace: prepared().workspace,
  }), 'thread', { preserveLibrary: true });
  view.rerender({ ...value });
  expect(preparePdfWorkspace).toHaveBeenCalledTimes(1);
});

it.each(['hidden', 'existing', 'unavailable', 'expired'])('does not create for %s scope', async kind => {
  const value = props();
  if (kind === 'hidden') value.active = false;
  if (kind === 'existing') value.snapshot.hub.workspace = prepared().workspace;
  if (['unavailable', 'expired'].includes(kind)) value.snapshot.hub.workspace.state = kind;
  await act(async () => renderHook(usePdfPreparation, { initialProps: value }));
  expect(preparePdfWorkspace).not.toHaveBeenCalled();
  expect(value.snapshot.applySnapshot).not.toHaveBeenCalled();
});

it('does not automatically replay an unconfirmed request; explicit retry uses the same owner', async () => {
  const value = props();
  preparePdfWorkspace.mockRejectedValueOnce(Error('PRIVATE'));
  const view = renderHook(usePdfPreparation, { initialProps: value });
  await waitFor(() => expect(view.result.current.status).toBe('unavailable'));
  view.rerender({ ...value });
  expect(preparePdfWorkspace).toHaveBeenCalledTimes(1);
  await act(async () => view.result.current.retry());
  expect(view.result.current.status).toBe('ready');
  expect(preparePdfWorkspace.mock.calls).toEqual([['thread'], ['thread', { retry: true }]]);
});

it.each([{ state: 'expired' }, { state: 'ready' }, { ...prepared(), workspace: { state: 'ready', entries: [] } }])(
  'never claims project readiness for an incomplete or expired reply', async reply => {
    const value = props(); preparePdfWorkspace.mockResolvedValue(reply);
    const view = renderHook(usePdfPreparation, { initialProps: value });
    await waitFor(() => expect(view.result.current.status).toBe(reply.state === 'expired' ? 'expired' : 'unavailable'));
    expect(value.snapshot.applySnapshot).not.toHaveBeenCalled();
  },
);

it('a retired thread cannot apply a late preparation reply', async () => {
  let complete;
  preparePdfWorkspace.mockReturnValue(new Promise(resolve => { complete = resolve; }));
  const value = props();
  const view = renderHook(usePdfPreparation, { initialProps: value });
  await waitFor(() => expect(preparePdfWorkspace).toHaveBeenCalled());
  value.owns.mockReturnValue(false);
  view.unmount();
  await act(async () => complete(prepared()));
  expect(value.snapshot.applySnapshot).not.toHaveBeenCalled();
});

it.each(['Not Found', 'pdf_project_not_found'])('only a confirmed ownership denial can replace the current thread (%s)', async detail => {
  const onThreadUnavailable = jest.fn();
  const value = props({ onThreadUnavailable });
  preparePdfWorkspace.mockRejectedValue({ response: { status: 404, data: { detail } } });
  const view = renderHook(usePdfPreparation, { initialProps: value });
  await waitFor(() => expect(view.result.current.status).toBe('unavailable'));
  expect(onThreadUnavailable).toHaveBeenCalledTimes(detail === 'pdf_project_not_found' ? 1 : 0);
  expect(preparePdfWorkspace).toHaveBeenCalledTimes(1);
});

it('uses the normalized production error code for an ownership denial', async () => {
  const onThreadUnavailable = jest.fn();
  preparePdfWorkspace.mockRejectedValue({ type: 'DomainError', status: 404, code: 'pdf_project_not_found' });
  const view = renderHook(usePdfPreparation, { initialProps: props({ onThreadUnavailable }) });
  await waitFor(() => expect(view.result.current.status).toBe('unavailable'));
  expect(onThreadUnavailable).toHaveBeenCalledWith('thread');
});
