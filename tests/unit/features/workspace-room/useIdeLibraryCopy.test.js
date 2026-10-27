import { act, renderHook } from '@testing-library/react';
import { useIdeLibraryCopy } from '@features/workspace-room/model/useIdeLibraryCopy';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ leaseIdeFile: jest.fn(), copyLibraryToIde: jest.fn() }));
const A = '00000000-0000-0000-0000-000000000001';
const B = '00000000-0000-0000-0000-000000000002';
const generation = 'a'.repeat(64);
const file = { file_id: '10000000-0000-0000-0000-000000000001', name: 'image.zip' };
const options = () => ({ threadId: 'thread', target: { repository_id: A, generation, name: 'Repo', blocked: false, refresh: jest.fn() }, active: true });
const ack = () => ({ repository_id: A, generation, path: file.name, written: true, kind: 'file', digest: 'b'.repeat(64), size: 300000 });
beforeEach(() => {
  jest.resetAllMocks();
  api.leaseIdeFile.mockResolvedValue({ repository_id: A, generation, fence: 9 });
  api.copyLibraryToIde.mockResolvedValue(ack());
});

it('copies a binary-size receipt only to the pinned repo and releases its exact path lease', async () => {
  const props = options(); const hook = renderHook(() => useIdeLibraryCopy(props));
  act(() => hook.result.current.choose(file));
  await act(async () => hook.result.current.submit());
  expect(api.copyLibraryToIde).toHaveBeenCalledTimes(1);
  expect(api.copyLibraryToIde.mock.calls[0].slice(0, 4)).toEqual(['thread', A, file.file_id, { path: file.name, generation, fence: 9 }]);
  expect(api.leaseIdeFile.mock.calls.at(-1).slice(0, 3)).toEqual(['thread', A, { path: file.name, generation, action: 'release', fence: 9 }]);
  expect(hook.result.current.done).toBe(true);
  expect(props.target.refresh).toHaveBeenCalledTimes(1);
});

it('does not duplicate a copy even before React renders its busy state', async () => {
  const hook = renderHook(() => useIdeLibraryCopy(options()));
  act(() => hook.result.current.choose(file));
  await act(async () => { await Promise.all([hook.result.current.submit(), hook.result.current.submit()]); });
  expect(api.copyLibraryToIde).toHaveBeenCalledTimes(1);
});

it.each([{ code: 'ide_write_unconfirmed' }, { code: 'constructor' }, { code: '__proto__' }, new Error('PRIVATE_BODY')])('freezes an unknown acknowledgement without automatic mutation replay', async error => {
  api.copyLibraryToIde.mockRejectedValue(error);
  const hook = renderHook(() => useIdeLibraryCopy(options()));
  act(() => hook.result.current.choose(file));
  await act(async () => hook.result.current.submit());
  expect(hook.result.current.uncertain).toBe(true);
  expect(hook.result.current.error).not.toContain('PRIVATE');
  act(() => hook.result.current.setPath('another.zip'));
  await act(async () => hook.result.current.submit());
  expect(hook.result.current.path).toBe(file.name);
  expect(api.copyLibraryToIde).toHaveBeenCalledTimes(1);
});

it.each([() => { throw new Error('read failed'); }, () => Promise.reject(new Error('read failed'))])('does not downgrade a confirmed copy when its independent refresh fails', async refresh => {
  const props = options(); props.target.refresh = refresh;
  const hook = renderHook(() => useIdeLibraryCopy(props));
  act(() => hook.result.current.choose(file));
  await act(async () => hook.result.current.submit());
  expect(hook.result.current.done).toBe(true);
  expect(hook.result.current.error).toBe('');
  expect(hook.result.current.uncertain).toBe(false);
});

it('shows the receipt immediately while retaining honest busy admission until lease cleanup retires', async () => {
  let release;
  api.leaseIdeFile.mockImplementation((thread, repo, data) => data.action === 'release'
    ? new Promise(done => { release = done; }) : Promise.resolve({ repository_id: A, generation, fence: 9 }));
  const hook = renderHook(() => useIdeLibraryCopy(options()));
  act(() => hook.result.current.choose(file));
  let pending; await act(async () => { pending = hook.result.current.submit(); });
  expect(hook.result.current.done).toBe(true);
  expect(hook.result.current.busy).toBe(true);
  act(() => hook.result.current.choose({ ...file, file_id: 'other' }));
  expect(hook.result.current.file.file_id).toBe(file.file_id);
  await act(async () => { release({ released: true }); await pending; });
  expect(hook.result.current.busy).toBe(false);
});

it('allows a corrected destination after a definite no-clobber conflict', async () => {
  api.copyLibraryToIde.mockRejectedValue({ code: 'ide_file_changed' });
  const hook = renderHook(() => useIdeLibraryCopy(options()));
  act(() => hook.result.current.choose(file));
  await act(async () => hook.result.current.submit());
  expect(hook.result.current.uncertain).toBe(false);
  act(() => hook.result.current.setPath('assets/other.zip'));
  expect(hook.result.current.path).toBe('assets/other.zip');
  expect(hook.result.current.error).toBe('');
});

it('does not dispatch a late acquired lease into a different selected repository', async () => {
  let resolve; api.leaseIdeFile.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const props = options(); const hook = renderHook(p => useIdeLibraryCopy(p), { initialProps: props });
  act(() => hook.result.current.choose(file));
  let pending; act(() => { pending = hook.result.current.submit(); });
  act(() => hook.rerender({ ...props, target: { ...props.target, repository_id: B } }));
  await act(async () => { resolve({ repository_id: A, generation, fence: 9 }); await pending; });
  expect(api.copyLibraryToIde).not.toHaveBeenCalled();
  expect(hook.result.current.file).toBeNull();
  expect(api.leaseIdeFile.mock.calls.at(-1)[1]).toBe(A);
  expect(props.target.refresh).not.toHaveBeenCalled();
});

it('rejects unsafe paths before acquiring a lease or admitting storage work', async () => {
  const hook = renderHook(() => useIdeLibraryCopy(options()));
  act(() => hook.result.current.choose(file));
  act(() => hook.result.current.setPath('../secret'));
  await act(async () => hook.result.current.submit());
  expect(hook.result.current.invalid).toBe(true);
  expect(api.leaseIdeFile).not.toHaveBeenCalled();
  expect(api.copyLibraryToIde).not.toHaveBeenCalled();
});

it('rejects captured path/clear actions after another repository owns the form', () => {
  const props = options(); const hook = renderHook(p => useIdeLibraryCopy(p), { initialProps: props });
  act(() => hook.result.current.choose(file));
  const oldPath = hook.result.current.setPath; const oldClear = hook.result.current.clear;
  act(() => hook.rerender({ ...props, target: { ...props.target, repository_id: B } }));
  act(() => hook.result.current.choose({ ...file, name: 'new.bin' }));
  act(() => { oldPath('old-secret-path'); oldClear(); });
  expect(hook.result.current.path).toBe('new.bin');
  expect(hook.result.current.file.name).toBe('new.bin');
});

it('returns keyboard focus to the original copy action after the inline form closes', async () => {
  const control = document.createElement('button'); document.body.append(control);
  const hook = renderHook(() => useIdeLibraryCopy(options()));
  act(() => hook.result.current.choose(file, control));
  await act(async () => hook.result.current.clear());
  expect(control).toHaveFocus(); control.remove();
});
