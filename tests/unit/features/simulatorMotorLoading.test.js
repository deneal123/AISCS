import { act, renderHook, waitFor } from '@testing-library/react';
import useMotorReadout from '../../../src/features/simulator/scene/useMotorReadout';
import { loadMotorReadout } from '../../../src/features/simulator/scene/motorReadout';

jest.mock('../../../src/features/simulator/scene/motorReadout', () => ({ loadMotorReadout: jest.fn() }));
beforeEach(() => jest.clearAllMocks());

test('late motor events cannot move limbs of a different selected record', async () => {
  let finish;
  loadMotorReadout.mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce('new-motor-events');
  const old = {}, next = {};
  const hook = renderHook(({ data }) => useMotorReadout(data), { initialProps: { data: old } });
  const signal = loadMotorReadout.mock.calls[0][1];
  hook.rerender({ data: next });
  expect(hook.result.current.data).toBeNull();
  await waitFor(() => expect(hook.result.current.data).toBe('new-motor-events'));
  expect(signal.aborted).toBe(true);
  await act(async () => { finish('old-motor-events'); });
  expect(hook.result.current.data).toBe('new-motor-events');
});

test('motor failure retains an explicit paused pose and read-only recovery', async () => {
  const source = {};
  loadMotorReadout.mockRejectedValueOnce(new Error('private')).mockResolvedValueOnce('verified');
  const hook = renderHook(() => useMotorReadout(source));
  await waitFor(() => expect(hook.result.current.error).toContain('Движение приостановлено'));
  expect(hook.result.current.data).toBeNull();
  expect(hook.result.current.error).not.toContain('private');
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.data).toBe('verified'));
});
