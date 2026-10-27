import { act, renderHook, waitFor } from '@testing-library/react';
import { getIdeAgentCommands } from '@shared/api/ide';
import { commandHistory, useIdeAgentCommands } from '@features/workspace-room/model/useIdeAgentCommands';

jest.mock('@shared/api/ide', () => ({ getIdeAgentCommands: jest.fn() }));
const props = { threadId: 'thread', repositoryId: 'repo', generation: 'a'.repeat(64), active: true, available: true };
const entry = { id: 'operation', profile: 'python_script', target: 'hello.py', state: 'running', result: null, verification: null };
const history = (entries = [entry]) => ({ repository_id: 'repo', generation: props.generation, entries });
beforeEach(() => jest.clearAllMocks());

it('reads without dispatch, projects closed fields, and keeps unknown cleanup blocking', async () => {
  getIdeAgentCommands.mockResolvedValue(history([{ ...entry, state: 'unknown', engine_id: 'private' }]));
  const { result } = renderHook(useIdeAgentCommands, { initialProps: props });
  await waitFor(() => expect(result.current.entries).toHaveLength(1));
  expect(result.current.pending).toBe(true);
  expect(result.current.entries[0]).not.toHaveProperty('engine_id');
  act(() => result.current.clear());
  expect(result.current.entries).toEqual([]);
  expect(result.current.pending).toBe(true); // Clear is display-only, not process cancellation.
});

it('rejects late output after repository switch and aborts the retired read', async () => {
  let resolve;
  getIdeAgentCommands.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  getIdeAgentCommands.mockRejectedValue(Error('offline'));
  const { result, rerender } = renderHook(useIdeAgentCommands, { initialProps: props });
  const signal = getIdeAgentCommands.mock.calls[0][3];
  rerender({ ...props, repositoryId: 'other' });
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(history()));
  expect(result.current.entries).toEqual([]);
});

it('read failure retains output, and retry is explicit and read-only', async () => {
  getIdeAgentCommands.mockResolvedValueOnce(history([{ ...entry, state: 'failed' }]));
  const { result } = renderHook(useIdeAgentCommands, { initialProps: props });
  await waitFor(() => expect(result.current.entries).toHaveLength(1));
  getIdeAgentCommands.mockRejectedValue(Error('offline'));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.error).toBe(true));
  expect(result.current.entries).toHaveLength(1);
  expect(getIdeAgentCommands).toHaveBeenCalledTimes(2);
});

it('rejects wrong generations, unknown enum values and oversized output', () => {
  expect(() => commandHistory({ ...history(), generation: 'other' }, 'repo', props.generation)).toThrow();
  expect(() => commandHistory(history([{ ...entry, state: '__proto__' }]), 'repo', props.generation)).toThrow();
  expect(() => commandHistory(history([{ ...entry, result: { stdout: 'x'.repeat(20001) } }]), 'repo', props.generation)).toThrow();
});
