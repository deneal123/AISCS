import { act, renderHook } from '@testing-library/react';
import { useWebSocketChat } from '@features/chat/model/useWebSocketChat';
import { cancelTask } from '@api/jobs';

jest.mock('@shared/hooks/useAppToast', () => ({ useAppToast: () => jest.fn() }));
jest.mock('@api/jobs', () => ({ cancelTask: jest.fn().mockResolvedValue(undefined) }));

const NativeSocket = global.WebSocket;
let sockets;
class Socket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  constructor(url) {
    this.url = url;
    this.readyState = Socket.CONNECTING;
    this.send = jest.fn();
    sockets.push(this);
  }
  close() { this.readyState = Socket.CLOSED; }
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  sockets = [];
  global.WebSocket = Socket;
});
afterEach(() => { global.WebSocket = NativeSocket; jest.useRealTimers(); });

function connect() {
  const onError = jest.fn();
  const hook = renderHook(() => useWebSocketChat('queue-fixture', { onError }));
  act(() => jest.advanceTimersByTime(50));
  return { ...hook, onError, socket: sockets[0] };
}
function open(socket) {
  act(() => { socket.readyState = Socket.OPEN; socket.onopen(); });
}
function reconnect(socket) {
  act(() => {
    socket.readyState = Socket.CLOSED;
    socket.onclose({ code: 1006 });
    jest.advanceTimersByTime(1050);
  });
  return sockets[sockets.length - 1];
}

it('delivers an initially queued request exactly once on successful connection', () => {
  const { result, socket } = connect();
  act(() => result.current.sendMessage('synthetic request'));
  expect(socket.send).not.toHaveBeenCalled();
  open(socket);
  expect(socket.send).toHaveBeenCalledTimes(1);
  const next = reconnect(socket);
  open(next);
  expect(next.send).not.toHaveBeenCalled();
});

it('does not dispatch a request cancelled before a server task ID exists', async () => {
  const { result, socket } = connect();
  act(() => result.current.sendMessage('', null, null, { confirmOfferId: 'fixture-offer' }));
  await act(async () => result.current.cancelJob());
  open(socket);
  expect(socket.send).not.toHaveBeenCalled();
  expect(cancelTask).not.toHaveBeenCalled();
});

it('does not replay a failed send after reporting a terminal error', () => {
  const { result, socket, onError } = connect();
  open(socket);
  socket.send.mockImplementation(() => { throw new Error('PRIVATE_SEND_BODY'); });
  act(() => result.current.sendMessage('synthetic request'));
  expect(onError).toHaveBeenCalledTimes(1);
  const next = reconnect(socket);
  open(next);
  expect(next.send).not.toHaveBeenCalled();
});

it('reports a queue flush failure instead of silently leaving the run waiting', () => {
  const { result, socket, onError } = connect();
  act(() => result.current.sendMessage('synthetic request'));
  socket.send.mockImplementation(() => { throw new Error('PRIVATE_FLUSH_BODY'); });
  open(socket);
  expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'transport' }));
  const next = reconnect(socket);
  open(next);
  expect(next.send).not.toHaveBeenCalled();
});

it('drops unsent work after a local socket failure', () => {
  const { result, socket } = connect();
  act(() => result.current.sendMessage('synthetic request'));
  act(() => socket.onerror());
  const next = reconnect(socket);
  open(next);
  expect(next.send).not.toHaveBeenCalled();
});

it('does not reconnect after an accepted socket is refused by the access policy', () => {
  const onError = jest.fn();
  const onDisconnect = jest.fn();
  const { result } = renderHook(() => useWebSocketChat('protected-thread', { onError, onDisconnect }));
  act(() => jest.advanceTimersByTime(50));
  const socket = sockets[0];
  open(socket);
  act(() => {
    socket.readyState = Socket.CLOSED;
    socket.onclose({ code: 1008, reason: 'PRIVATE_OWNER_POLICY_DETAIL' });
  });
  expect(onDisconnect).toHaveBeenCalledWith(expect.objectContaining({ code: 1008 }), false);
  expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'unauthorized' }));
  expect(onError.mock.calls[0][0].message).not.toContain('PRIVATE');
  expect(result.current.connectionState).toBe('error');
  act(() => jest.advanceTimersByTime(120000));
  expect(sockets).toHaveLength(1);
});

it.each(['open', 'message', 'error', 'close'])('ignores a retired thread socket %s event', (event) => {
  const callbacks = { onError: jest.fn(), onConnect: jest.fn(), onDisconnect: jest.fn(), onStreamChunk: jest.fn() };
  const hook = renderHook(({ thread }) => useWebSocketChat(thread, callbacks), { initialProps: { thread: 'one' } });
  act(() => jest.advanceTimersByTime(50));
  const old = sockets[0];
  hook.rerender({ thread: 'two' });
  act(() => jest.advanceTimersByTime(50));
  const current = sockets[1];
  act(() => hook.result.current.sendMessage('NEW_THREAD_FIXTURE'));
  act(() => {
    if (event === 'open') { old.readyState = Socket.OPEN; old.onopen(); }
    if (event === 'message') old.onmessage({ data: JSON.stringify({ type: 'stream_chunk', data: 'OLD_THREAD_FIXTURE' }) });
    if (event === 'error') old.onerror();
    if (event === 'close') old.onclose({ code: 1006 });
  });
  Object.values(callbacks).forEach((callback) => expect(callback).not.toHaveBeenCalled());
  expect(old.send).not.toHaveBeenCalled();
  open(current);
  expect(current.send).toHaveBeenCalledTimes(1);
  expect(JSON.parse(current.send.mock.calls[0][0]).text).toBe('NEW_THREAD_FIXTURE');
});

it('resets the replay cursor when the thread changes', () => {
  const hook = renderHook(({ thread }) => useWebSocketChat(thread), { initialProps: { thread: 'one' } });
  act(() => jest.advanceTimersByTime(50));
  open(sockets[0]);
  act(() => sockets[0].onmessage({ data: JSON.stringify({ type: 'heartbeat', id: 'fixture-cursor' }) }));
  const resumed = reconnect(sockets[0]);
  expect(resumed.url).toContain('last_id=fixture-cursor');
  hook.rerender({ thread: 'two' });
  act(() => jest.advanceTimersByTime(50));
  expect(sockets.at(-1).url).toContain('/two/ws');
  expect(sockets.at(-1).url).not.toContain('last_id=');
});

it('does not carry a retired heartbeat timeout into the new socket', () => {
  const { socket } = connect();
  open(socket);
  act(() => socket.onmessage({ data: JSON.stringify({ type: 'heartbeat' }) }));
  act(() => jest.advanceTimersByTime(41050));
  const next = sockets.at(-1);
  expect(next).not.toBe(socket);
  open(next);
  act(() => jest.advanceTimersByTime(20000));
  expect(next.readyState).toBe(Socket.OPEN);
});
