import { act, renderHook } from '@testing-library/react';
import { useIdeSetup } from '@features/workspace-room/model/useIdeSetup';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ registerIdeRepository: jest.fn(), provisionIdeRuntime: jest.fn() }));
const repo = '20000000-0000-0000-0000-000000000001';
const descriptor = { repository_id: repo, name: 'A', state: 'registered' };
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
beforeEach(() => jest.resetAllMocks());

it('rejects duplicate activation synchronously and late completion after thread change', async () => {
  const pending = deferred(); api.registerIdeRepository.mockReturnValue(pending.promise);
  const onCreated = jest.fn();
  const hook = renderHook(({ threadId }) => useIdeSetup({ threadId, repositoryId: '', active: true, onCreated, onStarted: jest.fn() }), { initialProps: { threadId: 'old' } });
  const oldCreate = hook.result.current.create;
  let first;
  act(() => { first = oldCreate('A'); void oldCreate('A'); });
  expect(api.registerIdeRepository).toHaveBeenCalledTimes(1);
  hook.rerender({ threadId: 'new' });
  expect(api.registerIdeRepository.mock.calls[0][2].aborted).toBe(true);
  await act(async () => { pending.resolve(descriptor); expect(await first).toBe(false); expect(await oldCreate('A')).toBe(false); });
  expect(onCreated).not.toHaveBeenCalled();
  expect(hook.result.current.busy).toBe('');
});

it('does not start from an inactive or retired repository callback', async () => {
  const onStarted = jest.fn();
  const hook = renderHook(({ repositoryId, active }) => useIdeSetup({ threadId: 'thread', repositoryId, active, onCreated: jest.fn(), onStarted }), { initialProps: { repositoryId: repo, active: true } });
  const oldStart = hook.result.current.start;
  hook.rerender({ repositoryId: 'other', active: true });
  await act(async () => expect(await oldStart()).toBe(false));
  hook.rerender({ repositoryId: 'other', active: false });
  await act(async () => expect(await hook.result.current.start()).toBe(false));
  expect(api.provisionIdeRuntime).not.toHaveBeenCalled();
  expect(onStarted).not.toHaveBeenCalled();
});

it('keeps an uncertain create intent across hide/reopen and freezes its original name', async () => {
  api.registerIdeRepository.mockRejectedValueOnce(Error('ack lost')).mockResolvedValue(descriptor);
  const onCreated = jest.fn();
  const hook = renderHook(({ active }) => useIdeSetup({ threadId: 'thread', repositoryId: repo, active, onCreated }), { initialProps: { active: true } });
  const retired = hook.result.current.create;
  await act(async () => expect(await retired('A')).toBe(false));
  const intent = api.registerIdeRepository.mock.calls[0][1];
  hook.rerender({ active: false }); hook.rerender({ active: true });
  expect(hook.result.current.locked).toBe(true);
  expect(hook.result.current.submittedName).toBe('A');
  expect(api.registerIdeRepository).toHaveBeenCalledTimes(1);
  await act(async () => expect(await retired('B')).toBe(false));
  await act(async () => expect(await hook.result.current.create('B')).toBe(true));
  expect(api.registerIdeRepository.mock.calls[1][1]).toEqual(intent);
  expect(onCreated).toHaveBeenCalledTimes(1);
  expect(hook.result.current.locked).toBe(false);
});

it('retires a hidden in-flight create but lets an explicit current retry reuse its identity', async () => {
  const pending = deferred(); api.registerIdeRepository.mockReturnValueOnce(pending.promise).mockResolvedValue(descriptor);
  const onCreated = jest.fn();
  const hook = renderHook(({ active }) => useIdeSetup({ threadId: 'thread', repositoryId: repo, active, onCreated }), { initialProps: { active: true } });
  let first;
  act(() => { first = hook.result.current.create('A'); });
  const intent = api.registerIdeRepository.mock.calls[0][1];
  hook.rerender({ active: false }); hook.rerender({ active: true });
  expect(api.registerIdeRepository.mock.calls[0][2].aborted).toBe(true);
  await act(async () => { pending.resolve(descriptor); expect(await first).toBe(false); });
  expect(onCreated).not.toHaveBeenCalled();
  expect(api.registerIdeRepository).toHaveBeenCalledTimes(1);
  await act(async () => expect(await hook.result.current.create('A')).toBe(true));
  expect(api.registerIdeRepository.mock.calls[1][1]).toEqual(intent);
  expect(onCreated).toHaveBeenCalledTimes(1);
});

it('does not leak an uncertain name or identity into another repository scope', async () => {
  api.registerIdeRepository.mockRejectedValueOnce(Error('ack lost')).mockResolvedValue(descriptor);
  const hook = renderHook(({ repositoryId }) => useIdeSetup({ threadId: 'thread', repositoryId, active: true, onCreated: jest.fn() }), { initialProps: { repositoryId: repo } });
  await act(async () => { await hook.result.current.create('A'); });
  const previous = api.registerIdeRepository.mock.calls[0][1];
  hook.rerender({ repositoryId: 'other' });
  expect(hook.result.current.locked).toBe(false);
  expect(hook.result.current.submittedName).toBe('');
  await act(async () => { await hook.result.current.create('B'); });
  expect(api.registerIdeRepository.mock.calls[1][1].name).toBe('B');
  expect(api.registerIdeRepository.mock.calls[1][1].creation_intent_id).not.toBe(previous.creation_intent_id);
});

it('rejects an old start callback after the same repository is hidden and reopened', async () => {
  const hook = renderHook(({ active }) => useIdeSetup({ threadId: 'thread', repositoryId: repo, active, onStarted: jest.fn() }), { initialProps: { active: true } });
  const retired = hook.result.current.start;
  hook.rerender({ active: false }); hook.rerender({ active: true });
  await act(async () => expect(await retired()).toBe(false));
  expect(api.provisionIdeRuntime).not.toHaveBeenCalled();
});
