import { act, renderHook, waitFor } from '@testing-library/react';
import { executeIdeCommand, getIdeCommand, getIdeAgentCommands } from '@shared/api/ide';
import { useIdeConsole } from '@features/workspace-room/model/useIdeConsole';

jest.mock('@shared/api/ide', () => ({ executeIdeCommand: jest.fn(), getIdeCommand: jest.fn(), getIdeAgentCommands: jest.fn() }));
const props = { threadId: 'thread', repositoryId: 'repo', generation: 'a'.repeat(64), active: true, available: true };
const completed = id => ({ execution_id: id, repository_id: 'repo', generation: props.generation,
  state: 'completed', result: { exit_code: 0, stdout: 'Hello!\n', stderr: '', duration_sec: 0.1, timed_out: false, truncated: false } });
beforeEach(() => {
  jest.clearAllMocks();
  getIdeAgentCommands.mockResolvedValue({ repository_id: 'repo', generation: props.generation, entries: [] });
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { randomUUID: () => 'command-id' } });
});

it('runs only on explicit submit and clears private history on repository switch', async () => {
  const changed = jest.fn();
  executeIdeCommand.mockResolvedValue(completed('command-id'));
  const { result, rerender } = renderHook(value => useIdeConsole({ ...value, onChanged: changed }), { initialProps: props });
  expect(executeIdeCommand).not.toHaveBeenCalled();
  act(() => result.current.setDraft('python main.py'));
  await act(async () => result.current.run());
  expect(result.current.entries[0]).toMatchObject({ command: 'python main.py', state: 'completed' });
  expect(changed).toHaveBeenCalledTimes(1);
  expect(executeIdeCommand).toHaveBeenCalledTimes(1);
  rerender({ ...props, repositoryId: 'other' });
  expect(result.current.entries).toEqual([]); expect(result.current.draft).toBe('');
});

it('prevents double activation and ignores late output for another generation', async () => {
  let finish;
  executeIdeCommand.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { result, rerender } = renderHook(useIdeConsole, { initialProps: props });
  act(() => result.current.setDraft('python main.py'));
  let task;
  act(() => { task = result.current.run(); void result.current.run(); });
  expect(executeIdeCommand).toHaveBeenCalledTimes(1);
  rerender({ ...props, generation: 'b'.repeat(64) });
  await act(async () => { finish(completed('command-id')); await task; });
  expect(result.current.entries).toEqual([]);
});

it('reconciles a lost response only through GET, never by reposting', async () => {
  executeIdeCommand.mockRejectedValue(Error('network'));
  getIdeCommand.mockResolvedValue(completed('command-id'));
  const { result } = renderHook(useIdeConsole, { initialProps: props });
  act(() => result.current.setDraft('python main.py'));
  await act(async () => result.current.run());
  expect(result.current.entries[0].state).toBe('unknown');
  await act(async () => result.current.check('command-id'));
  expect(result.current.entries[0].state).toBe('completed');
  expect(getIdeCommand).toHaveBeenCalledWith('thread', 'repo', 'command-id');
  expect(executeIdeCommand).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(result.current.busy).toBe(''));
});

it('cannot dispatch in unavailable or blocked runtime', async () => {
  const { result, rerender } = renderHook(useIdeConsole, { initialProps: { ...props, available: false } });
  act(() => result.current.setDraft('touch file'));
  await act(async () => result.current.run());
  rerender({ ...props, blocked: true });
  await act(async () => result.current.run());
  expect(executeIdeCommand).not.toHaveBeenCalled();
});
