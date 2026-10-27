import { act, renderHook, waitFor } from '@testing-library/react';
import { getDocumentSources } from '@api/chat';
import { useDocumentSources } from '@features/workspace-room/model/useDocumentSources';

jest.mock('@api/chat', () => ({ getDocumentSources: jest.fn() }));
const project = { path: 'documents/paper', revision: 'r1', source_digest: 'a'.repeat(64) };
const initial = { threadId: 't1', project, enabled: false };
const response = { revision: 'r1', source_digest: project.source_digest, unresolved_count: 0,
  sources: [{ source_id: 2, title: 'Реальный источник', year: '2024' }] };
beforeEach(() => { jest.clearAllMocks(); getDocumentSources.mockResolvedValue(response); });

it('loads only on demand and exposes document labels without inventing missing metadata', async () => {
  const view = renderHook((props) => useDocumentSources(props), { initialProps: initial });
  expect(getDocumentSources).not.toHaveBeenCalled();
  view.rerender({ ...initial, enabled: true });
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  expect(view.result.current.sources[0].label).toBe('Реальный источник · 2024');
  expect(view.result.current.sources[0].author).toBeUndefined();
  view.rerender({ ...initial, enabled: true });
  expect(getDocumentSources).toHaveBeenCalledTimes(1);
  view.rerender(initial);
  view.rerender({ ...initial, enabled: true });
  expect(getDocumentSources).toHaveBeenCalledTimes(1);
});

it('explicit retry revalidates project facts before repeating the private read', async () => {
  getDocumentSources.mockRejectedValueOnce(new Error('private response'));
  const refreshProject = jest.fn().mockResolvedValue(project);
  const view = renderHook(() => useDocumentSources({ ...initial, enabled: true, refreshProject }));
  await waitFor(() => expect(view.result.current.status).toBe('unavailable'));
  await act(async () => view.result.current.retry());
  expect(refreshProject).toHaveBeenCalledWith(project.path);
  expect(view.result.current.status).toBe('ready');
});

it('retires late data and callbacks on project change and unmount', async () => {
  let finish;
  getDocumentSources.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const view = renderHook((props) => useDocumentSources(props), { initialProps: { ...initial, enabled: true } });
  const oldLoad = view.result.current.load;
  view.rerender({ ...initial, enabled: true, project: { ...project, path: 'documents/other' } });
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  expect(getDocumentSources.mock.calls[0][2].signal.aborted).toBe(true);
  await act(async () => { finish({ ...response, sources: [{ source_id: 1, title: 'Старое' }] }); await oldLoad(); });
  expect(view.result.current.sources[0].source_id).toBe(2);
  expect(getDocumentSources).toHaveBeenCalledTimes(2);
  const latest = view.result.current.load;
  view.unmount();
  await act(async () => latest());
  expect(getDocumentSources).toHaveBeenCalledTimes(2);
});

it.each([
  { ...response, revision: 'r2' },
  { ...response, source_digest: 'b'.repeat(64) },
  { ...response, sources: [response.sources[0], response.sources[0]] },
])('does not offer stale or ambiguous citations and retries a read only', async (bad) => {
  getDocumentSources.mockResolvedValueOnce(bad);
  const view = renderHook(() => useDocumentSources({ ...initial, enabled: true }));
  await waitFor(() => expect(view.result.current.status).toBe('unavailable'));
  expect(view.result.current.sources).toEqual([]);
  await act(async () => view.result.current.load());
  expect(view.result.current.status).toBe('ready');
  expect(getDocumentSources).toHaveBeenCalledTimes(2);
});
