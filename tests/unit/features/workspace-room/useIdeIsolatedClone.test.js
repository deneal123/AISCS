import { act, renderHook } from '@testing-library/react';
import { useIdeIsolatedClone } from '@features/workspace-room/model/useIdeIsolatedClone';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ cloneIdeRepository: jest.fn(), getIdeClone: jest.fn() }));
const source = '00000000-0000-0000-0000-000000000001';
const target = '00000000-0000-0000-0000-000000000002';
const response = (state = 'complete', id = target) => ({ state, repository: { repository_id: id, name: 'Cloned', state: 'registered' }, code: null });
const values = { origin: 'https://github.com/owner/repo', branch: 'main' };
const props = () => ({ threadId: 'thread', repositoryId: source, active: true, onCloned: jest.fn() });
beforeEach(() => { jest.resetAllMocks(); api.cloneIdeRepository.mockResolvedValue(response()); api.getIdeClone.mockResolvedValue(response()); });

it('accepts only the isolated acknowledged destination and pins the request', async () => {
  const options = props(); const hook = renderHook(() => useIdeIsolatedClone(options));
  await act(async () => expect(await hook.result.current.run(values)).toBe(true));
  expect(options.onCloned).toHaveBeenCalledWith(response().repository);
  expect(api.cloneIdeRepository.mock.calls[0][1]).toMatchObject({ source_repository_id: source, ...values });
  expect(api.cloneIdeRepository.mock.calls[0][1].intent_id).toMatch(/^[a-f0-9-]{36}$/);
  await act(async () => hook.result.current.run({ ...values, branch: 'other' }));
  expect(api.cloneIdeRepository).toHaveBeenCalledTimes(1);
  expect(api.getIdeClone).toHaveBeenCalledTimes(1);
});

it('reconciles a lost reply with GET, never with an automatic POST retry', async () => {
  api.cloneIdeRepository.mockRejectedValueOnce(new Error('PRIVATE'));
  const options = props(); const hook = renderHook(() => useIdeIsolatedClone(options));
  await act(async () => expect(await hook.result.current.run(values)).toBe(true));
  expect(api.cloneIdeRepository).toHaveBeenCalledTimes(1);
  expect(api.getIdeClone).toHaveBeenCalledTimes(1);
  expect(options.onCloned).toHaveBeenCalledTimes(1);
});

it('keeps an unknown request immutable and reuses its intent on explicit recovery', async () => {
  api.cloneIdeRepository.mockRejectedValueOnce(new Error('PRIVATE'));
  api.getIdeClone.mockRejectedValueOnce(new Error('PRIVATE')).mockRejectedValueOnce({ status: 404 });
  const options = props(); const hook = renderHook(() => useIdeIsolatedClone(options));
  await act(async () => hook.result.current.run(values));
  expect(hook.result.current.locked).toBe(true);
  expect(hook.result.current.error).not.toContain('PRIVATE');
  expect(options.onCloned).not.toHaveBeenCalled();
  const original = api.cloneIdeRepository.mock.calls[0][1];
  await act(async () => hook.result.current.run(values));
  expect(api.cloneIdeRepository.mock.calls[1][1]).toEqual(original);
});

it.each(['running', 'unconfirmed', 'failed'])('observes %s without repeating the Git command', async state => {
  api.cloneIdeRepository.mockResolvedValue(response(state)); api.getIdeClone.mockResolvedValue(response(state));
  const options = props(); const hook = renderHook(() => useIdeIsolatedClone(options));
  await act(async () => hook.result.current.run(values));
  await act(async () => hook.result.current.run(values));
  expect(api.cloneIdeRepository).toHaveBeenCalledTimes(1);
  expect(options.onCloned).not.toHaveBeenCalled();
  expect(hook.result.current.result.state).toBe(state);
});

it('continues a reserved destination only after explicit recovery and rejects a changed target', async () => {
  api.cloneIdeRepository.mockResolvedValueOnce(response('preparing'));
  api.getIdeClone.mockResolvedValue(response('preparing'));
  const options = props(); const hook = renderHook(() => useIdeIsolatedClone(options));
  await act(async () => hook.result.current.run(values));
  expect(api.cloneIdeRepository).toHaveBeenCalledTimes(1);
  await act(async () => hook.result.current.run(values));
  expect(api.cloneIdeRepository).toHaveBeenCalledTimes(2);
  expect(options.onCloned).toHaveBeenCalledTimes(1);
  api.getIdeClone.mockResolvedValue(response('complete', '00000000-0000-0000-0000-000000000003'));
  await act(async () => hook.result.current.run(values));
  expect(options.onCloned).toHaveBeenCalledTimes(1);
});

it('aborts retired work and cannot open the old result while inactive', async () => {
  const options = props(); const hook = renderHook(p => useIdeIsolatedClone(p), { initialProps: options });
  await act(async () => hook.result.current.run(values));
  const open = hook.result.current.open;
  hook.rerender({ ...options, active: false });
  act(() => open());
  expect(options.onCloned).toHaveBeenCalledTimes(1);
  let resolve; api.getIdeClone.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  hook.rerender(options);
  let running; act(() => { running = hook.result.current.run(values); });
  const signal = api.getIdeClone.mock.calls.at(-1)[2];
  hook.rerender({ ...options, threadId: 'other' });
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(response()); await running; });
  expect(options.onCloned).toHaveBeenCalledTimes(1);
});

it('restores a destination after reload and resumes the original source/intent, not a new project', async () => {
  const options = { ...props(), repositoryId: target };
  const hook = renderHook(() => useIdeIsolatedClone(options));
  const attempt = { ...response('preparing'), intent_id: '10000000-0000-0000-0000-000000000001', source_repository_id: source,
    request: { origin: 'https://github.com/owner/repo.git', branch: 'main' } };
  api.getIdeClone.mockResolvedValue(response('preparing'));
  act(() => expect(hook.result.current.restore(attempt)).toBe(true));
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
  await act(async () => expect(await hook.result.current.run()).toBe(true));
  expect(api.cloneIdeRepository.mock.calls[0][1]).toEqual({ intent_id: attempt.intent_id, source_repository_id: source, ...attempt.request });
  expect(options.onCloned).toHaveBeenCalledWith(response().repository);
});
