import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import usePopulationFeedback from '../../../src/features/simulator/recording/usePopulationFeedback';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  feedbackRuns: jest.fn(), get: jest.fn(), eventsUrl: jest.fn(),
} }));

function Probe({ source }) {
  const state = usePopulationFeedback(source, false);
  return <span>{state.status}{state.connectionLost ? ':offline' : ''}{state.progress ? `:${state.progress.iteration}:${state.progress.done}` : ''}</span>;
}

test('retries a transient status failure without losing the running job', async () => {
  jest.useFakeTimers();
  const original = global.WebSocket;
  global.WebSocket = class { close() {} };
  simulationApi.eventsUrl.mockReturnValue('ws://localhost/test');
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'feedback', state: 'running' }] });
  simulationApi.get.mockResolvedValueOnce({ id: 'feedback', state: 'running' })
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ id: 'feedback', state: 'running' });
  try {
    render(<Probe source={{ id: 'source', state: 'completed', configuration: {} }} />);
    await waitFor(() => expect(screen.getByText('running')).toBeInTheDocument());
    await act(async () => { jest.advanceTimersByTime(4000); });
    expect(screen.getByText('running:offline')).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(screen.getByText('running')).toBeInTheDocument();
    expect(simulationApi.get).toHaveBeenCalledTimes(3);
  } finally { global.WebSocket = original; jest.useRealTimers(); }
});

test('shows progress only for the active feedback run', async () => {
  const original = global.WebSocket;
  let socket;
  global.WebSocket = class { constructor() { socket = this; } close() {} };
  simulationApi.eventsUrl.mockReturnValue('ws://localhost/test');
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'feedback', state: 'running' }] });
  simulationApi.get.mockResolvedValue({ id: 'feedback', state: 'running' });
  try {
    render(<Probe source={{ id: 'source', state: 'completed', configuration: {} }} />);
    await waitFor(() => expect(screen.getByText('running')).toBeInTheDocument());
    act(() => socket.onmessage({ data: JSON.stringify({ event: { run_id: 'feedback', progress: {
      phase: 'feedback_cells', iteration: 2, done: 3, total: 46,
    } } }) }));
    expect(screen.getByText('running:2:3')).toBeInTheDocument();
    act(() => socket.onmessage({ data: JSON.stringify({ event: { run_id: 'other', progress: {
      phase: 'feedback_cells', iteration: 9, done: 9, total: 46,
    } } }) }));
    expect(screen.getByText('running:2:3')).toBeInTheDocument();
  } finally { global.WebSocket = original; }
});
