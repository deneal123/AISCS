import { act, renderHook } from '@testing-library/react';
import { useWorkUploadSelection } from '../../../../src/features/workspace-room/model/useWorkUploadSelection';

const file = new File(['body'], 'brief.txt');
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

it('blocks simultaneous starts before a busy rerender', async () => {
  const request = deferred();
  const onUpload = jest.fn(() => request.promise);
  const { result } = renderHook(() => useWorkUploadSelection({ scope: 'a', onUpload }));
  let pending;
  act(() => {
    pending = result.current.start(file);
    result.current.start(file);
  });
  expect(onUpload).toHaveBeenCalledTimes(1);
  await act(async () => { request.resolve({ cancelled: true }); await pending; });
  expect(result.current.state).toBe('cancelled');
});

it('retains File and intent across presentation rerenders', async () => {
  const onUpload = jest.fn().mockResolvedValue({ cancelled: true });
  const { result, rerender } = renderHook(() => useWorkUploadSelection({ scope: 'a', onUpload }));
  await act(async () => result.current.start(file));
  const intent = result.current.selected.intentId;
  rerender();
  expect(result.current.selected.file).toBe(file);
  await act(async () => result.current.start(file, result.current.selected.intentId));
  expect(onUpload.mock.calls[1][1].uploadIntentId).toBe(intent);
});

it('ignores old progress and outcomes after thread change', async () => {
  const request = deferred();
  const onUpload = jest.fn(() => request.promise);
  const onPartial = jest.fn();
  const { result, rerender } = renderHook(({ scope }) => useWorkUploadSelection({
    scope, onUpload, onPartial,
  }), { initialProps: { scope: 'a' } });
  let pending;
  act(() => { pending = result.current.start(file); });
  rerender({ scope: 'b' });
  await act(async () => {
    onUpload.mock.calls[0][1].onProgress(90);
    request.resolve({ ok: true, outcome: 'library_saved' });
    await pending;
  });
  expect(result.current.selected).toBeNull();
  expect(result.current.state).toBe('idle');
  expect(result.current.progress).toBe(0);
  expect(onPartial).not.toHaveBeenCalled();
});

it('allows bounded retry when an upload callback rejects', async () => {
  const onUpload = jest.fn().mockRejectedValue(new Error('PRIVATE-ERROR'));
  const { result } = renderHook(() => useWorkUploadSelection({ scope: 'a', onUpload }));
  await act(async () => result.current.start(file));
  expect(result.current.state).toBe('error');
  const intent = result.current.selected.intentId;
  await act(async () => result.current.start(file, intent));
  expect(onUpload).toHaveBeenCalledTimes(2);
  expect(onUpload.mock.calls[1][1].uploadIntentId).toBe(intent);
  expect(JSON.stringify(result.current)).not.toContain('PRIVATE-ERROR');
});

it('pins the upload destination mode across drawer and surface changes', async () => {
  const onUpload = jest.fn().mockResolvedValue({ cancelled: true });
  const hook = renderHook(({ uploadOptions }) => useWorkUploadSelection({ scope: 'a', onUpload, uploadOptions }), { initialProps: { uploadOptions: { libraryOnly: true } } });
  await act(async () => hook.result.current.start(file));
  const original = hook.result.current.selected;
  hook.rerender({ uploadOptions: undefined });
  await act(async () => hook.result.current.start(original.file, original.intentId, original.options));
  expect(onUpload.mock.calls[1][1]).toMatchObject({ libraryOnly: true, uploadIntentId: original.intentId });
});
