import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FieldRerecordPreview from '../../../src/features/simulator/field/FieldRerecordPreview';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { rerecordPreview: jest.fn() } }));
jest.mock('../../../src/features/simulator/recording/SignalPlot', () => ({ preview, comparison }) => <div>Новая: {preview.signal_uv.join(',')} · Исходная трасса: {comparison.signal_uv.join(',')}</div>);

test('previews saved currents and discards an obsolete response after moving a contact', async () => {
  let finish;
  simulationApi.rerecordPreview.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const props = { runId: 'one', electrode: [1, 2, 3], reference: [4, 5, 6], valid: true,
    original: { time_ms: [0, 1], neural_uv: [0, 2] } };
  const { rerender } = render(<FieldRerecordPreview {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр E1 − REF' }));
  const signal = simulationApi.rerecordPreview.mock.calls[0][2];
  rerender(<FieldRerecordPreview {...props} electrode={[2, 2, 3]} />);
  expect(signal.aborted).toBe(true);
  finish({ cells: 2, time_ms: [0, 1], neural_uv: [0, 1] });
  await waitFor(() => expect(screen.queryByLabelText('Предпросмотр новой записи')).not.toBeInTheDocument());
  simulationApi.rerecordPreview.mockResolvedValueOnce({ cells: 2, time_ms: [0, 1], neural_uv: [0, 1] });
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр E1 − REF' }));
  expect(await screen.findByLabelText('Предпросмотр новой записи')).toBeInTheDocument();
  expect(screen.getByText(/Исходная трасса: 0,2/)).toBeInTheDocument();
  expect(simulationApi.rerecordPreview.mock.calls[1][1].electrode_um).toEqual([2, 2, 3]);
  rerender(<FieldRerecordPreview {...props} electrode={[3, 2, 3]} />);
  expect(screen.queryByLabelText('Предпросмотр новой записи')).not.toBeInTheDocument();
});

test('compares matching channels and reports acquisition saturation', async () => {
  simulationApi.rerecordPreview.mockResolvedValueOnce({ cells: 2, time_ms: [0, 1], neural_uv: [0, 1], total_uv: [2, 3],
    acquisition: { filtered_total_uv: [4, 5], valid_samples: [true, false], saturated_samples: [false, true],
      mask_intervals: [{ start_ms: 0, end_ms: .5, valid: true, saturated: false }, { start_ms: .5, end_ms: 1, valid: false, saturated: true }] } });
  render(<FieldRerecordPreview runId="run" electrode={[1, 2, 3]} reference={[4, 5, 6]} valid
    original={{ time_ms: [0, 1], neural_uv: [0, 2], total_uv: [3, 4], acquisition: { filtered_total_uv: [5, 6],
      mask_intervals: [{ start_ms: 0, end_ms: 1, valid: false, saturated: true }] } }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр E1 − REF' }));
  await screen.findByLabelText('Предпросмотр новой записи');
  fireEvent.click(screen.getByRole('button', { name: 'С артефактом' }));
  expect(screen.getByText(/Новая: 2,3 · Исходная трасса: 3,4/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Регистрация' }));
  expect(screen.getByText(/Новая: 4,5 · Исходная трасса: 5,6/)).toBeInTheDocument();
  expect(screen.getByText(/есть насыщение/)).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Маска новой записи' }).querySelectorAll('rect')).toHaveLength(2);
  expect(screen.getByRole('img', { name: 'Маска исходной записи' }).querySelectorAll('rect')).toHaveLength(1);
});
