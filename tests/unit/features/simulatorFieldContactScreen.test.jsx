import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FieldContactScreen from '../../../src/features/simulator/field/FieldContactScreen';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { contactScreen: jest.fn(), contactPositions: jest.fn() } }));
const simulation = { source_um: [1, 2, 3], return_um: [4, 5, 6], electrode_um: [7, 8, 9],
  reference_um: [10, 11, 12], clearance_um: 1 };
beforeEach(() => jest.resetAllMocks());

test('reports an unavailable audit without claiming contact safety', async () => {
  simulationApi.contactScreen.mockRejectedValue({ status: 503 });
  render(<FieldContactScreen sceneRunId="run" simulation={simulation} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('индекс контактов пока недоступен');
  expect(screen.queryByText(/пересечения не найдены/)).not.toBeInTheDocument();
});

test('reports conservative overlaps by contact', async () => {
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [
    { body_id: 1, contact_indices: [0, 2] }, { body_id: 2, contact_indices: [0] },
  ] });
  render(<FieldContactScreen sceneRunId="run" simulation={simulation} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('STIM+, E1; клеток — 2');
  expect(screen.getByRole('alert')).toHaveTextContent('Измените положение контактов');
});

test('clears and aborts stale results after any contact changes', async () => {
  let resolve;
  simulationApi.contactScreen.mockImplementation(() => new Promise(done => { resolve = done; }));
  const { rerender } = render(<FieldContactScreen sceneRunId="run" simulation={simulation} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  const signal = simulationApi.contactScreen.mock.calls[0][2];
  rerender(<FieldContactScreen sceneRunId="run" simulation={{ ...simulation, reference_um: [11, 11, 12] }} />);
  expect(signal.aborted).toBe(true);
  resolve({ potential_intersections: [] });
  await waitFor(() => expect(screen.queryByText(/пересечения не найдены/)).not.toBeInTheDocument());
  expect(screen.getByText(/не выполнена/)).toBeInTheDocument();
});

test('labels no overlaps as limited to the audited snapshot', async () => {
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [] });
  render(<FieldContactScreen sceneRunId="run" simulation={simulation} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  expect(await screen.findByRole('status')).toHaveTextContent('свойства тканей не подтверждены');
});

test('checks candidate points and applies only an explicitly selected one', async () => {
  const select = jest.fn();
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ body_id: 1, contact_indices: [2] }] });
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [{ contact_indices: [0, 2, 3, 4, 5] }] });
  render(<FieldContactScreen sceneRunId="run" simulation={simulation} onSelectContact={select} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  await screen.findByText(/Возможное пересечение/);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить соседние точки' }));
  const candidate = await screen.findByRole('button', { name: '32 / 8 / 9' });
  expect(select).not.toHaveBeenCalled();
  expect(screen.getByText(/Поверхность тела и ткани не проверяются/)).toBeInTheDocument();
  fireEvent.click(candidate);
  expect(select).toHaveBeenCalledWith(2, [32, 8, 9]);
});

test('a superseded candidate search cannot apply stale points', async () => {
  let resolve;
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ body_id: 1, contact_indices: [0] }] });
  simulationApi.contactPositions.mockImplementation(() => new Promise(done => { resolve = done; }));
  const { rerender } = render(<FieldContactScreen sceneRunId="run" simulation={simulation} onSelectContact={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  await screen.findByText(/Возможное пересечение/);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить соседние точки' }));
  const signal = simulationApi.contactPositions.mock.calls[0][2];
  rerender(<FieldContactScreen sceneRunId="run" simulation={{ ...simulation, source_um: [2, 2, 3] }} onSelectContact={jest.fn()} />);
  expect(signal.aborted).toBe(true);
  resolve({ potential_intersections: [] });
  await waitFor(() => expect(screen.queryByText(/Без пересечений в проверенном снимке/)).not.toBeInTheDocument());
});

test('allows a wider search after all nearby positions intersect', async () => {
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ body_id: 1, contact_indices: [0] }] });
  simulationApi.contactPositions.mockResolvedValueOnce({ potential_intersections: [{ contact_indices: [0, 1, 2, 3, 4, 5] }] })
    .mockResolvedValueOnce({ potential_intersections: [] });
  render(<FieldContactScreen sceneRunId="run" simulation={simulation} onSelectContact={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  await screen.findByText(/Возможное пересечение/);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить соседние точки' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить дальше · 100 мкм' }));
  await screen.findByText('Без пересечений в проверенном снимке:');
  expect(simulationApi.contactPositions.mock.calls[1][1].positions_um[0]).toEqual([-99, 2, 3]);
  expect(screen.getByText(/расстоянии 100 мкм/)).toBeInTheDocument();
});
