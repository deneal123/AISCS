import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SimulationSidebar from '../../../src/features/simulator/components/SimulationSidebar';

test('shows CNS history, delegates selection and retains pagination', () => {
  const select = jest.fn();
  const more = jest.fn();
  const create = jest.fn();
  const history = { runs: [
    { id: 'old', title: 'Старый опыт', state: 'completed', created_at: '2026-10-30T12:00:00Z', configuration: { model_id: 'legacy' } },
    { id: 'cns', title: 'Опыт ЦНС', state: 'completed', created_at: '2026-10-30T12:00:00Z', configuration: { model_id: 'cns' } },
  ], nextOffset: 30, loading: false, error: '', more, retry: jest.fn() };
  render(<SimulationSidebar history={history} modelId="cns" selectedId="cns"
    onNew={create} onSelect={select} onClose={jest.fn()} />);
  expect(screen.queryByText('Старый опыт')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Опыт ЦНС'));
  expect(select).toHaveBeenCalledWith(history.runs[1]);
  fireEvent.click(screen.getByRole('button', { name: 'Новый опыт' }));
  fireEvent.click(screen.getByRole('button', { name: 'Ещё опыты' }));
  expect(create).toHaveBeenCalledTimes(1);
  expect(more).toHaveBeenCalledTimes(1);
});

test('confirms removal of a completed run and prevents removing a running run', async () => {
  const onRemove = jest.fn().mockResolvedValue();
  const history = { runs: [
    { id: 'done', title: 'Завершённый', state: 'completed', created_at: '2026-10-30', configuration: { model_id: 'cns' } },
    { id: 'busy', title: 'Выполняется', state: 'running', created_at: '2026-10-30', configuration: { model_id: 'cns' } },
  ], nextOffset: null, loading: false, error: '' };
  render(<SimulationSidebar history={history} modelId="cns" onRemove={onRemove} />);
  expect(screen.getByRole('button', { name: 'Удалить из списка: Выполняется' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Удалить из списка: Завершённый' }));
  expect(onRemove).not.toHaveBeenCalled();
  expect(screen.getByText(/Связанные расчёты и файлы останутся/)).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Удалить' })); });
  await waitFor(() => expect(onRemove).toHaveBeenCalledWith(history.runs[0]));
});
