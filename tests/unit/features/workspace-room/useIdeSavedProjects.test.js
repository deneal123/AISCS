import { act, renderHook, waitFor } from '@testing-library/react';
import { useIdeSavedProjects } from '@features/workspace-room/model/useIdeSavedProjects';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ getIdeCheckpointCapabilities: jest.fn(), listIdeCheckpoints: jest.fn(), getIdeCheckpoint: jest.fn(), discardIdeCheckpoint: jest.fn(), abandonIdeCheckpoint: jest.fn(), saveIdeCheckpoint: jest.fn(), reconcileIdeCheckpoint: jest.fn(), restoreIdeCheckpoint: jest.fn(), reconcileIdeRestore: jest.fn() }));
const mockToast = jest.fn();
jest.mock('@shared/hooks/useAppToast', () => ({ useAppToast: () => mockToast }));
const repo = '10000000-0000-4000-8000-000000000001';
const id = '20000000-0000-4000-8000-000000000001';
const gen = 'a'.repeat(64);
const history = (items = [], runtime = 'ready', last_restore = null) => ({ repository_id: repo, items, truncated: false,
  usage: { used_bytes: 1024, max_bytes: 100000, max_snapshot_bytes: 10000 }, runtime: { generation: gen, state: runtime }, last_restore });
const item = { checkpoint_id: id, state: 'published', size_bytes: 100, created_at: '2026-10-18T17:00:00Z', is_current: true };
const result = { repository_id: repo, ...item };
const pending = { ...item, state: 'pending', is_current: false, can_discard: true };
const unfinished = { repository_id: repo, ...pending, collected: false };
const removed = { ...unfinished, state: 'retired', can_discard: false, collected: true, cleanup_pending: false };
const props = { threadId: 'thread', repositoryId: repo, active: true, generation: gen, blocked: false };
const mount = async (extra = {}) => {
  const hook = renderHook(value => useIdeSavedProjects(value), { initialProps: { ...props, ...extra } });
  await waitFor(() => expect(hook.result.current.history).not.toBeNull()); return hook;
};
beforeEach(() => {
  jest.resetAllMocks(); sessionStorage.clear();
  api.getIdeCheckpointCapabilities.mockResolvedValue({ enabled: true });
  api.listIdeCheckpoints.mockResolvedValue(history());
  api.saveIdeCheckpoint.mockImplementation(async (_thread, _repo, data) => ({ ...result, checkpoint_id: data.checkpoint_id }));
  api.getIdeCheckpoint.mockResolvedValue(unfinished);
  api.discardIdeCheckpoint.mockResolvedValue(removed);
});

it('blocks duplicate dispatch synchronously and saves only frozen public identity', async () => {
  let complete; api.saveIdeCheckpoint.mockImplementation((_thread, _repo, data) => new Promise(resolve => { complete = () => resolve({ ...result, checkpoint_id: data.checkpoint_id }); }));
  const hook = await mount(); let first;
  act(() => { first = hook.result.current.save(); void hook.result.current.save(); });
  expect(api.saveIdeCheckpoint).toHaveBeenCalledTimes(1);
  expect(api.saveIdeCheckpoint.mock.calls[0][2]).toEqual({ checkpoint_id: expect.any(String), base_checkpoint_id: null, generation: gen });
  await act(async () => { complete(); expect(await first).toBe(true); });
  expect(hook.result.current.intent).toBeNull(); expect(mockToast).toHaveBeenCalledTimes(1);
});

it('lost acknowledgement survives remount; reads never repeat Save and explicit retry keeps its UUID', async () => {
  api.saveIdeCheckpoint.mockRejectedValueOnce(Error('PRIVATE')); const hook = await mount();
  await act(async () => expect(await hook.result.current.save()).toBe(false));
  const frozen = api.saveIdeCheckpoint.mock.calls[0][2]; hook.unmount();
  const next = await mount(); expect(next.result.current.intent.checkpoint_id).toBe(frozen.checkpoint_id);
  expect(api.saveIdeCheckpoint).toHaveBeenCalledTimes(1);
  await act(async () => expect(await next.result.current.save()).toBe(false));
  expect(api.saveIdeCheckpoint).toHaveBeenCalledTimes(1);
  await act(async () => expect(await next.result.current.retry()).toBe(true));
  expect(api.saveIdeCheckpoint.mock.calls[1][2]).toEqual(frozen);
  expect(next.result.current.error).not.toContain('PRIVATE');
});

it('scope retirement prevents a late result and captured old callback from affecting another repository', async () => {
  let complete; api.saveIdeCheckpoint.mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  const hook = await mount(); const oldSave = hook.result.current.save; let promise;
  act(() => { promise = oldSave(); });
  hook.rerender({ ...props, repositoryId: 'other', active: false });
  await act(async () => { complete(result); expect(await promise).toBe(false); expect(await oldSave()).toBe(false); });
  expect(mockToast).not.toHaveBeenCalled(); expect(hook.result.current.outcome).toBe('');
});

it('does not dispatch while a file or another action owns the scene', async () => {
  const hook = await mount({ blocked: true });
  await act(async () => expect(await hook.result.current.save()).toBe(false));
  expect(api.saveIdeCheckpoint).not.toHaveBeenCalled();
});

it('a historical publication is saved but never described as replacing current files', async () => {
  api.saveIdeCheckpoint.mockImplementation(async (_thread, _repo, data) => ({ ...result, checkpoint_id: data.checkpoint_id, is_current: false }));
  const hook = await mount(); await act(async () => expect(await hook.result.current.save()).toBe(true));
  expect(hook.result.current.outcome).toContain('Текущая версия проекта не заменена');
});

it('discovers restore from server on reload but adopts it only after explicit active proof', async () => {
  const restored = { repository_id: repo, restore_id: id, checkpoint_id: id, state: 'pending', active: false, generation: null };
  api.listIdeCheckpoints.mockResolvedValue(history([item], 'expired', restored));
  api.reconcileIdeRestore.mockResolvedValue({ ...restored, state: 'published', active: false });
  const onRestored = jest.fn(); const hook = await mount({ onRestored });
  expect(api.restoreIdeCheckpoint).not.toHaveBeenCalled();
  await act(async () => expect(await hook.result.current.checkRestore()).toBe(false));
  expect(onRestored).not.toHaveBeenCalled();
  api.reconcileIdeRestore.mockResolvedValue({ ...restored, state: 'published', active: true, generation: 'b'.repeat(64) });
  await act(async () => expect(await hook.result.current.checkRestore()).toBe(true));
  expect(onRestored).toHaveBeenCalledTimes(1);
});

it('only restores a published version after expiry and retains frozen generation on unknown acknowledgement', async () => {
  api.listIdeCheckpoints.mockResolvedValue(history([item], 'expired'));
  api.restoreIdeCheckpoint.mockRejectedValue(Error());
  const hook = await mount(); await act(async () => expect(await hook.result.current.restore(item)).toBe(false));
  expect(api.restoreIdeCheckpoint.mock.calls[0][2]).toEqual({ restore_id: expect.any(String), checkpoint_id: id, base_generation: gen });
  expect(hook.result.current.intent.base_generation).toBe(gen);
  expect(api.restoreIdeCheckpoint).toHaveBeenCalledTimes(1);
});

it('a failed post-success history refresh does not retract the confirmed save', async () => {
  const hook = await mount(); api.listIdeCheckpoints.mockRejectedValueOnce(Error());
  await act(async () => { await hook.result.current.save(); });
  expect(hook.result.current.intent).toBeNull(); expect(hook.result.current.outcome).toBe('Проект сохранён.');
  expect(hook.result.current.error).toContain('подтверждён'); expect(mockToast).toHaveBeenCalledTimes(1);
});

it('keeps safe deletion proof after reconciliation cannot find uploaded bytes', async () => {
  api.listIdeCheckpoints.mockResolvedValue(history([pending]));
  api.reconcileIdeCheckpoint.mockRejectedValue(Error('PRIVATE_STORAGE'));
  const hook = await mount(); await act(async () => expect(await hook.result.current.check(pending)).toBe(false));
  expect(hook.result.current.inspected.can_discard).toBe(true);
  expect(api.discardIdeCheckpoint).not.toHaveBeenCalled();
  api.listIdeCheckpoints.mockResolvedValue(history());
  await act(async () => expect(await hook.result.current.discard(pending)).toBe(true));
  expect(api.discardIdeCheckpoint).toHaveBeenCalledTimes(1);
  expect(api.discardIdeCheckpoint.mock.calls[0].slice(0, 3)).toEqual(['thread', repo, id]);
  expect(hook.result.current.intent).toBeNull();
  expect(hook.result.current.outcome).toContain('Файлы проекта не изменены');
  expect(api.saveIdeCheckpoint).not.toHaveBeenCalled();
});

it('revalidates deletion eligibility and never deletes a snapshot published since confirmation', async () => {
  api.listIdeCheckpoints.mockResolvedValue(history([pending])); api.getIdeCheckpoint.mockResolvedValue(result);
  const hook = await mount(); await act(async () => expect(await hook.result.current.discard(pending)).toBe(false));
  expect(api.discardIdeCheckpoint).not.toHaveBeenCalled();
  expect(hook.result.current.inspected.state).toBe('published');
  expect(hook.result.current.outcome).toContain('Удаление не выполнено');
});

it('never deletes an unsettled upload or a malformed/foreign status response', async () => {
  api.listIdeCheckpoints.mockResolvedValue(history([pending]));
  const hook = await mount();
  for (const status of [{ ...unfinished, can_discard: false }, { ...unfinished, checkpoint_id: '30000000-0000-4000-8000-000000000001' }, { ...unfinished, can_discard: 'yes' }]) {
    api.getIdeCheckpoint.mockResolvedValueOnce(status);
    await act(async () => expect(await hook.result.current.discard(pending)).toBe(false));
  }
  expect(api.discardIdeCheckpoint).not.toHaveBeenCalled();
});

it('a lost delete acknowledgement is recovered by passive proof, without repeating deletion or Save', async () => {
  sessionStorage.setItem('gpthub.ide.pending:thread:' + repo, JSON.stringify({ kind: 'save', checkpoint_id: id, generation: gen, base_checkpoint_id: null }));
  api.listIdeCheckpoints.mockResolvedValue(history([pending])); api.discardIdeCheckpoint.mockRejectedValue(Error());
  const hook = await mount(); await act(async () => expect(await hook.result.current.discard(pending)).toBe(false));
  expect(hook.result.current.intent.checkpoint_id).toBe(id);
  api.getIdeCheckpoint.mockResolvedValue(removed); api.listIdeCheckpoints.mockResolvedValue(history());
  await act(async () => expect(await hook.result.current.check()).toBe(true));
  expect(hook.result.current.intent).toBeNull(); expect(hook.result.current.history.items).toEqual([]);
  expect(api.discardIdeCheckpoint).toHaveBeenCalledTimes(1);
  expect(api.reconcileIdeCheckpoint).not.toHaveBeenCalled(); expect(api.saveIdeCheckpoint).not.toHaveBeenCalled();
});

it('retains quota and pending identity until collected is confirmed, not merely a delete acknowledgement', async () => {
  sessionStorage.setItem('gpthub.ide.pending:thread:' + repo, JSON.stringify({ kind: 'save', checkpoint_id: id, generation: gen, base_checkpoint_id: null }));
  const cleanup = { ...unfinished, state: 'retired', cleanup_pending: true };
  api.listIdeCheckpoints.mockResolvedValue(history([pending])); api.discardIdeCheckpoint.mockResolvedValue(cleanup);
  const hook = await mount(); await act(async () => expect(await hook.result.current.discard(pending)).toBe(false));
  expect(hook.result.current.intent.checkpoint_id).toBe(id); expect(hook.result.current.history.usage.used_bytes).toBe(1024);
  expect(hook.result.current.outcome).toContain('Место пока не освобождено');
});

it('late deletion after scope retirement cannot dispatch a POST or update the new scene', async () => {
  api.listIdeCheckpoints.mockResolvedValue(history([pending])); let finish;
  api.getIdeCheckpoint.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const hook = await mount(); let promise; const oldDiscard = hook.result.current.discard;
  act(() => { promise = oldDiscard(pending); });
  hook.rerender({ ...props, active: false });
  await act(async () => { finish(unfinished); expect(await promise).toBe(false); });
  hook.rerender(props); await waitFor(() => expect(hook.result.current.history).not.toBeNull());
  await act(async () => expect(await oldDiscard(pending)).toBe(false));
  expect(api.discardIdeCheckpoint).not.toHaveBeenCalled();
});

it('duplicate deletion admits one GET and one POST, and preserves an unrelated pending Save', async () => {
  const other = '30000000-0000-4000-8000-000000000001';
  sessionStorage.setItem('gpthub.ide.pending:thread:' + repo, JSON.stringify({ kind: 'save', checkpoint_id: other, generation: gen, base_checkpoint_id: null }));
  api.listIdeCheckpoints.mockResolvedValue(history([pending])); let finish;
  api.discardIdeCheckpoint.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const hook = await mount(); let promise;
  await act(async () => { promise = hook.result.current.discard(pending); void hook.result.current.discard(pending); });
  expect(api.getIdeCheckpoint).toHaveBeenCalledTimes(1); expect(api.discardIdeCheckpoint).toHaveBeenCalledTimes(1);
  await act(async () => { finish(removed); expect(await promise).toBe(true); });
  expect(hook.result.current.intent.checkpoint_id).toBe(other);
});

it('revocation clears only its pending Save without claiming deletion or releasing held quota', async () => {
  sessionStorage.setItem('gpthub.ide.pending:thread:' + repo, JSON.stringify({ kind: 'save', checkpoint_id: id, generation: gen, base_checkpoint_id: null }));
  const uploading = { ...pending, can_discard: false, can_abandon: true };
  const revoked = { repository_id: repo, ...uploading, state: 'retired', can_abandon: false, collected: false };
  api.listIdeCheckpoints.mockResolvedValue(history([uploading])); api.getIdeCheckpoint.mockResolvedValue({ repository_id: repo, ...uploading });
  api.abandonIdeCheckpoint.mockResolvedValue(revoked);
  const hook = await mount();
  await act(async () => expect(await hook.result.current.abandon(uploading)).toBe(true));
  expect(api.abandonIdeCheckpoint.mock.calls[0].slice(0, 3)).toEqual(['thread', repo, id]);
  expect(api.discardIdeCheckpoint).not.toHaveBeenCalled(); expect(hook.result.current.intent).toBeNull();
  expect(hook.result.current.history.usage.used_bytes).toBe(1024);
  expect(hook.result.current.outcome).toBe('Попытка отменена. Файлы проекта не изменены.');
  await act(async () => expect(await hook.result.current.save()).toBe(true));
  expect(api.saveIdeCheckpoint).toHaveBeenCalledTimes(1);
  expect(api.saveIdeCheckpoint.mock.calls[0][2].checkpoint_id).not.toBe(id);
});

it('lost revocation acknowledgement retains the intent until terminal proof and never repeats POST', async () => {
  sessionStorage.setItem('gpthub.ide.pending:thread:' + repo, JSON.stringify({ kind: 'save', checkpoint_id: id, generation: gen, base_checkpoint_id: null }));
  const uploading = { ...pending, can_discard: false, can_abandon: true };
  api.listIdeCheckpoints.mockResolvedValue(history([uploading])); api.getIdeCheckpoint.mockResolvedValue({ repository_id: repo, ...uploading });
  api.abandonIdeCheckpoint.mockRejectedValue(Error());
  const hook = await mount(); await act(async () => expect(await hook.result.current.abandon(uploading)).toBe(false));
  expect(hook.result.current.intent.checkpoint_id).toBe(id);
  api.getIdeCheckpoint.mockResolvedValue({ repository_id: repo, ...uploading, state: 'retired', can_abandon: false });
  await act(async () => expect(await hook.result.current.abandon(uploading)).toBe(true));
  expect(api.abandonIdeCheckpoint).toHaveBeenCalledTimes(1); expect(api.discardIdeCheckpoint).not.toHaveBeenCalled();
  expect(hook.result.current.intent).toBeNull(); expect(hook.result.current.history.usage.used_bytes).toBe(1024);
});

it('publication winning the revocation race cannot be abandoned', async () => {
  const uploading = { ...pending, can_discard: false, can_abandon: true };
  api.listIdeCheckpoints.mockResolvedValue(history([uploading])); api.getIdeCheckpoint.mockResolvedValue(result);
  const hook = await mount(); await act(async () => expect(await hook.result.current.abandon(uploading)).toBe(false));
  expect(api.abandonIdeCheckpoint).not.toHaveBeenCalled(); expect(hook.result.current.outcome).toContain('Отмена не выполнена');
});
