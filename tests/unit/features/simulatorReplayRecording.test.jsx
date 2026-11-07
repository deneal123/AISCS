import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ReplayRecording from '../../../src/features/simulator/recording/ReplayRecording';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { replays: jest.fn(), get: jest.fn() } }));
jest.mock('../../../src/features/simulator/recording/SignalPlot', () => ({ preview }) => <div>Трасса: {preview.signal_uv.length}</div>);

beforeEach(() => jest.resetAllMocks());

test('shows a completed one-cell result with its limitations', async () => {
  simulationApi.replays.mockResolvedValue({ items: [{ id: 'replay', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'replay', configuration: { simulation: {
    electrode_um: [1, 2, 3], reference_um: [4, 5, 6],
  } }, result: { preview: { body_id: '42', time_ms: [0, 1], signal_uv: [0, 1] } } });
  render(<ReplayRecording sourceId="source" timeMs={0} onTime={() => {}} />);
  expect(await screen.findByText('Дополнительная запись нейрона 42')).toBeInTheDocument();
  expect(screen.getByText(/не запись всей ЦНС/)).toBeInTheDocument();
  expect(screen.getByText('Трасса: 2')).toBeInTheDocument();
  expect(screen.getByText(/Контакты этой записи заданы отдельно/)).toBeInTheDocument();
  expect(screen.getByText(/E1: \(1, 2, 3\)/)).toBeInTheDocument();
  expect(simulationApi.replays).toHaveBeenCalledWith('source', expect.any(AbortSignal));
});

test('reports an unavailable result and retries', async () => {
  simulationApi.replays.mockRejectedValueOnce(new Error()).mockResolvedValueOnce({ items: [] });
  render(<ReplayRecording sourceId="source" timeMs={0} onTime={() => {}} />);
  expect(await screen.findByRole('status')).toHaveTextContent('Дополнительная запись недоступна');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Повторить' })); });
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  expect(simulationApi.replays).toHaveBeenCalledTimes(2);
});

test('identifies an older completed trace when the most recent calculation failed', async () => {
  simulationApi.replays.mockResolvedValue({ items: [
    { id: 'new', state: 'failed' }, { id: 'old', state: 'completed' },
  ] });
  simulationApi.get.mockResolvedValue({ id: 'old', result: { preview: {
    body_id: '42', time_ms: [0, 1], signal_uv: [0, 1],
  } } });
  render(<ReplayRecording sourceId="source" timeMs={0} onTime={() => {}} />);
  expect(await screen.findByText(/последний расчёт завершился ошибкой/)).toBeInTheDocument();
});
