import { act, renderHook, waitFor } from '@testing-library/react';
import { leaseIdeFile, moveIdeFile, readIdeFile, writeIdeFile } from '@api/ide';
import { useIdeEditor } from '@features/workspace-room/model/useIdeEditor';

jest.mock('@api/ide', () => ({ leaseIdeFile: jest.fn(), readIdeFile: jest.fn(), writeIdeFile: jest.fn(), moveIdeFile: jest.fn() }));
const repositoryId = '00000000-0000-0000-0000-000000000001';
const generation = 'a'.repeat(64);
const file = { path: 'main.py', kind: 'text', content: 'old', digest: 'b'.repeat(64), truncated: false };
const props = { threadId: 'thread', repositoryId, generation, active: true, onWritten: jest.fn(), onMoved: jest.fn(), onRecovered: jest.fn() };
const actual = (content = 'old', digest = file.digest) => ({ ...file, repository_id: repositoryId, generation, content, digest, size: content.length });
beforeEach(() => {
  jest.resetAllMocks();
  leaseIdeFile.mockImplementation(async (_t, _r, value) => ({ repository_id: repositoryId, generation, path: value.path, fence: 3, expires_at: Math.floor(Date.now() / 1000) + 30 }));
  writeIdeFile.mockImplementation(async (_t, _r, value) => ({ repository_id: repositoryId, generation, path: value.path, written: true,
    kind: value.operation === 'directory' ? 'dir' : 'file', digest: value.operation === 'directory' ? null : 'c'.repeat(64), size: value.content.length }));
  moveIdeFile.mockImplementation(async (_t, _r, value) => ({ repository_id: repositoryId, generation, path: value.destination, moved_from: value.path, moved: true, size: 3 }));
  readIdeFile.mockResolvedValue(actual());
});

it('leases both paths before moving and updates consumers only after a matching acknowledgement', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => expect(await hook.result.current.move(file, 'src/main.py')).toBe(true));
  expect(leaseIdeFile.mock.calls.filter(call => call[2].action === 'acquire').map(call => call[2].path)).toEqual(['main.py', 'src/main.py']);
  expect(moveIdeFile.mock.calls[0][2]).toMatchObject({ path: 'main.py', destination: 'src/main.py', expected_digest: file.digest, fence: 3, destination_fence: 3 });
  expect(props.onMoved).toHaveBeenCalledWith(expect.objectContaining({ moved_from: 'main.py', path: 'src/main.py' }));
});

it('never moves a dirty file or publishes a mismatched move acknowledgement', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('draft'));
  await act(async () => expect(await hook.result.current.move(file, 'src/main.py')).toBe(false));
  expect(moveIdeFile).not.toHaveBeenCalled();
  act(() => hook.result.current.discard());
  moveIdeFile.mockResolvedValue({ repository_id: repositoryId, generation, path: 'wrong.py', moved_from: file.path, moved: true, size: 3 });
  await act(async () => expect(await hook.result.current.move(file, 'src/main.py')).toBe(false));
  expect(props.onMoved).not.toHaveBeenCalled();
});

it('creates a file explicitly and saves edits with the confirmed base digest', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => expect(await hook.result.current.create('main.py', 'file')).toBe(true));
  expect(writeIdeFile.mock.calls[0][2]).toMatchObject({ path: 'main.py', expected_digest: null, content: '', fence: 3 });
  act(() => hook.result.current.change('new'));
  expect(hook.result.current.dirty).toBe(true);
  await act(async () => hook.result.current.save());
  expect(writeIdeFile.mock.calls[1][2]).toMatchObject({ expected_digest: 'c'.repeat(64), content: 'new' });
  expect(hook.result.current.dirty).toBe(false);
});

it('creates a folder without inventing an editable file or a Git commit', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.create('src', 'directory'));
  expect(props.onWritten).toHaveBeenCalledWith(expect.objectContaining({ kind: 'dir' }), '');
  expect(hook.result.current.file).toBeNull();
});

it('preserves the draft on a rejected write and revokes edit permission', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  writeIdeFile.mockRejectedValue({ status: 409 });
  await act(async () => hook.result.current.save());
  expect(hook.result.current.file).toMatchObject({ content: 'my draft', original: 'old', fence: 0 });
  expect(hook.result.current.dirty).toBe(true);
  expect(props.onWritten).not.toHaveBeenCalled();
});

it('does not dispatch a write when the lease cannot be acquired', async () => {
  leaseIdeFile.mockRejectedValue(Error('PRIVATE'));
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => expect(await hook.result.current.create('main.py', 'file')).toBe(false));
  expect(writeIdeFile).not.toHaveBeenCalled();
  expect(hook.result.current.error).not.toContain('PRIVATE');
});

it('rejects captured actions and late leases after a repository switch', async () => {
  let resolve;
  leaseIdeFile.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const hook = renderHook(options => useIdeEditor(options), { initialProps: props });
  const create = hook.result.current.create;
  let task;
  act(() => { task = create('main.py', 'file'); });
  await waitFor(() => expect(resolve).toEqual(expect.any(Function)));
  hook.rerender({ ...props, repositoryId: '00000000-0000-0000-0000-000000000002' });
  await act(async () => { resolve({ repository_id: repositoryId, generation, path: 'main.py', fence: 3, expires_at: 9999999999 }); await task; await create('old.py', 'file'); });
  expect(writeIdeFile).not.toHaveBeenCalled();
  expect(hook.result.current.file).toBeNull();
});

it('retains unsaved text but refuses to save it against a replacement generation', async () => {
  const hook = renderHook(options => useIdeEditor(options), { initialProps: props });
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('unsaved'));
  hook.rerender({ ...props, generation: 'd'.repeat(64) });
  expect(hook.result.current.file).toMatchObject({ content: 'unsaved', fence: 0 });
  await act(async () => hook.result.current.save());
  expect(writeIdeFile).not.toHaveBeenCalled();
});

it('checks the file under its lease before restoring edit permission without rebasing a draft', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  writeIdeFile.mockRejectedValue({ status: 409, code: 'ide_file_changed' });
  await act(async () => hook.result.current.save());
  readIdeFile.mockResolvedValue(actual('someone else', 'd'.repeat(64)));
  await act(async () => expect(await hook.result.current.edit(hook.result.current.file)).toBe(false));
  expect(hook.result.current.file).toMatchObject({ content: 'my draft', original: 'old', digest: file.digest, fence: 0 });
  expect(hook.result.current.conflict.actualContent).toBe('someone else');
  await act(async () => expect(await hook.result.current.save()).toBe(false));
  expect(writeIdeFile).toHaveBeenCalledTimes(1);
});

it('reconciles a lost acknowledgement by read only and loads the reviewed version only explicitly', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  writeIdeFile.mockRejectedValue({ status: 503 });
  await act(async () => hook.result.current.save());
  readIdeFile.mockResolvedValue(actual('my draft', 'd'.repeat(64)));
  await act(async () => expect(await hook.result.current.inspect()).toBe(true));
  expect(hook.result.current.dirty).toBe(true);
  expect(hook.result.current.conflict.actualContent).toBe('my draft');
  expect(hook.result.current.file.digest).toBe(file.digest);
  act(() => expect(hook.result.current.loadActual()).toBe(true));
  expect(hook.result.current.file).toMatchObject({ content: 'my draft', original: 'my draft', digest: 'd'.repeat(64), fence: 0 });
  expect(hook.result.current.dirty).toBe(false);
  expect(props.onRecovered).toHaveBeenCalledWith(expect.objectContaining({ content: 'my draft', generation }));
  expect(props.onWritten).not.toHaveBeenCalled();
  expect(writeIdeFile).toHaveBeenCalledTimes(1);
});

it('keeps a draft and offers another read when the comparison is unavailable or incomplete', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  readIdeFile.mockRejectedValueOnce(Error('PRIVATE'));
  await act(async () => expect(await hook.result.current.inspect()).toBe(false));
  expect(hook.result.current.conflict.actualContent).toBeNull();
  expect(hook.result.current.error).not.toContain('PRIVATE');
  expect(hook.result.current.file.content).toBe('my draft');
  act(() => expect(hook.result.current.loadActual()).toBe(false));
  readIdeFile.mockResolvedValue({ ...actual('preview'), truncated: true, digest: null });
  await act(async () => expect(await hook.result.current.inspect()).toBe(false));
  act(() => expect(hook.result.current.loadActual()).toBe(false));
  expect(hook.result.current.file.content).toBe('my draft');
});

it('ignores a late comparison and captured recovery/discard actions after a repository switch', async () => {
  const hook = renderHook(options => useIdeEditor(options), { initialProps: props });
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  const old = hook.result.current;
  let resolve;
  readIdeFile.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  let task;
  act(() => { task = old.inspect(); });
  await waitFor(() => expect(readIdeFile).toHaveBeenCalledTimes(2));
  hook.rerender({ ...props, repositoryId: '00000000-0000-0000-0000-000000000002' });
  await act(async () => { resolve(actual('late')); await task; });
  expect(hook.result.current.file).toBeNull();
  expect(await old.inspect()).toBe(false);
  expect(old.loadActual()).toBe(false);
  expect(old.discard()).toBe(false);
  expect(props.onRecovered).not.toHaveBeenCalled();
});

it('can copy a retained draft after generation replacement but never write it to that generation', async () => {
  const writeText = jest.fn().mockResolvedValue();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  const hook = renderHook(options => useIdeEditor(options), { initialProps: props });
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  hook.rerender({ ...props, generation: 'd'.repeat(64) });
  await act(async () => expect(await hook.result.current.edit(hook.result.current.file)).toBe(false));
  await act(async () => expect(await hook.result.current.copyDraft()).toBe(true));
  expect(writeText).toHaveBeenCalledWith('my draft');
  await act(async () => expect(await hook.result.current.save()).toBe(false));
  expect(writeIdeFile).not.toHaveBeenCalled();
});

it('does not turn an acknowledged save into an uncertain write if a read consumer throws', async () => {
  const hook = renderHook(() => useIdeEditor({ ...props, onWritten: () => { throw Error('PRIVATE'); } }));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  await act(async () => expect(await hook.result.current.save()).toBe(true));
  expect(hook.result.current.dirty).toBe(false);
  expect(hook.result.current.error).toBe('');
});

it('keeps controls busy until the failed-write lease is released and prevents duplicate recovery reads', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  writeIdeFile.mockRejectedValue({ status: 503 });
  let release;
  leaseIdeFile.mockImplementation(async (_t, _r, value) => value.action === 'release'
    ? new Promise(done => { release = done; })
    : { repository_id: repositoryId, generation, path: value.path, fence: 3, expires_at: 9999999999 });
  let saving;
  act(() => { saving = hook.result.current.save(); });
  await waitFor(() => expect(release).toEqual(expect.any(Function)));
  expect(hook.result.current.busy).toBe('save');
  expect(await hook.result.current.inspect()).toBe(false);
  expect(readIdeFile).toHaveBeenCalledTimes(1);
  await act(async () => { release({}); await saving; });
  expect(hook.result.current.busy).toBe('');
  expect(hook.result.current.file.content).toBe('my draft');
});

it('refuses mismatched read metadata and preserves manual clipboard recovery on rejection', async () => {
  const hook = renderHook(() => useIdeEditor(props));
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  readIdeFile.mockResolvedValue({ ...actual(), generation: 'd'.repeat(64) });
  await act(async () => expect(await hook.result.current.inspect()).toBe(false));
  act(() => expect(hook.result.current.loadActual()).toBe(false));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: jest.fn().mockRejectedValue(Error('PRIVATE')) } });
  await act(async () => expect(await hook.result.current.copyDraft()).toBe(false));
  expect(hook.result.current.error).toContain('вручную');
  expect(hook.result.current.error).not.toContain('PRIVATE');
  expect(hook.result.current.file.content).toBe('my draft');
});

it('revokes writes during runtime verification but keeps copying available and waits for old lease cleanup', async () => {
  const writeText = jest.fn().mockResolvedValue();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  const hook = renderHook(options => useIdeEditor(options), { initialProps: { ...props, verified: true } });
  await act(async () => hook.result.current.edit(file));
  act(() => hook.result.current.change('my draft'));
  let finishRelease;
  leaseIdeFile.mockImplementation(async (_t, _r, value) => value.action === 'release'
    ? new Promise(done => { finishRelease = done; })
    : { repository_id: repositoryId, generation, path: value.path, fence: 4, expires_at: 9999999999 });
  hook.rerender({ ...props, verified: false });
  await waitFor(() => expect(finishRelease).toEqual(expect.any(Function)));
  expect(hook.result.current.file).toMatchObject({ content: 'my draft', fence: 0 });
  expect(hook.result.current.canInspect).toBe(false);
  await act(async () => expect(await hook.result.current.save()).toBe(false));
  await act(async () => expect(await hook.result.current.copyDraft()).toBe(true));
  expect(writeText).toHaveBeenCalledWith('my draft');
  hook.rerender({ ...props, verified: true });
  let editing;
  act(() => { editing = hook.result.current.edit(hook.result.current.file); });
  expect(leaseIdeFile.mock.calls.filter(call => call[2].action === 'acquire')).toHaveLength(1);
  await act(async () => { finishRelease({}); await editing; });
  expect(hook.result.current.file).toMatchObject({ content: 'my draft', original: 'old', fence: 4 });
  expect(writeIdeFile).not.toHaveBeenCalled();
});

it('bounds long lease timers and revokes permission only at the actual absolute expiry', async () => {
  jest.useFakeTimers();
  try {
    const expires = Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
    leaseIdeFile.mockImplementation(async (_t, _r, value) => ({ repository_id: repositoryId, generation, path: value.path, fence: 3, expires_at: expires }));
    const hook = renderHook(() => useIdeEditor(props));
    await act(async () => hook.result.current.edit(file));
    await act(async () => jest.advanceTimersByTime(2 ** 31 - 1));
    expect(hook.result.current.file.fence).toBe(3);
    await act(async () => jest.advanceTimersByTime(expires * 1000 - Date.now() + 1));
    expect(hook.result.current.file.fence).toBe(0);
    expect(hook.result.current.error).toContain('Право на правку истекло');
    hook.unmount();
  } finally { jest.useRealTimers(); }
});

it('retains an unchanged editor snapshot after runtime loss and marks it for the navigation guard', async () => {
  const onDirtyChange = jest.fn();
  const hook = renderHook(options => useIdeEditor({ ...options, onDirtyChange }), { initialProps: props });
  await act(async () => hook.result.current.edit(file));
  expect(hook.result.current.dirty).toBe(false);
  hook.rerender({ ...props, generation: undefined, verified: false });
  expect(hook.result.current.file).toMatchObject({ content: 'old', original: 'old', fence: 0, detached: true });
  expect(hook.result.current.dirty).toBe(true);
  expect(onDirtyChange).toHaveBeenLastCalledWith(true, 'ide');
  expect(hook.result.current.canReacquire).toBe(false);
  await act(async () => expect(await hook.result.current.save()).toBe(false));
  expect(writeIdeFile).not.toHaveBeenCalled();
});
