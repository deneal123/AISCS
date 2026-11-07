import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import PopulationTargetReplay from '../../../src/features/simulator/recording/PopulationTargetReplay';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  preparePopulationTarget: jest.fn(), createPopulationTarget: jest.fn(), get: jest.fn(), populationTargetRuns: jest.fn(),
} }));
jest.mock('../../../src/features/simulator/recording/SignalPlot', () => () => <div>График</div>);

test('requires explicit parameters and binds the calculation to the verified source', async () => {
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { randomUUID: () => '00000000-0000-4000-8000-000000000001' } });
  simulationApi.populationTargetRuns.mockResolvedValue({ items: [] });
  simulationApi.preparePopulationTarget.mockResolvedValue({ source_ids: [10], graph_manifest_sha256: 'a',
    sha256: 'b', manifest_sha256: 'c', duration_ms: 200 });
  simulationApi.createPopulationTarget.mockResolvedValue({ id: 'target', parent_run_id: 'source', configuration: { target_id: 20 }, state: 'completed',
    result: { preview: { source_cells: 1, target_id: 20, time_ms: [0, 1], neural_uv: [0, 1], timing_mode: 'upper_bound' } } });
  render(<PopulationTargetReplay runId="source" nodeId="20" candidates={[{ source_id: 10, events: 2, intervals_available: true }]} />);
  await waitFor(() => expect(simulationApi.populationTargetRuns).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByRole('checkbox', { name: /10 · событий: 2/ })).toBeEnabled());
  fireEvent.click(screen.getByText('Рассчитать ответ нейрона'));
  expect(screen.getByText(/События графа округлены вперёд до шага 1 мс/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: /10 · событий: 2/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Повтор по верхней границе интервала' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Повтор по нижней границе интервала' }));
  expect(screen.getByRole('checkbox', { name: 'Повтор по верхней границе интервала' })).not.toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Повтор по нижней границе интервала' })).toBeChecked();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Повтор по верхней границе интервала' }));
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeDisabled();
  for (const [label, value] of [['Задержка, мс', '1'], ['Проводимость, мкСм', '.001'],
    ['Нарастание, мс', '.2'], ['Спад, мс', '2'], ['Потенциал реверсии, мВ', '0'],
    ['Допуск геометрии, мкм', '2']]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createPopulationTarget).toHaveBeenCalledTimes(1));
  expect(simulationApi.createPopulationTarget.mock.calls[0][0]).toMatchObject({
    parent_run_id: 'source', configuration: { source_package_sha256: 'b', source_manifest_sha256: 'c',
      target_id: 20, source_ids: [10], timing_mode: 'upper_bound', synapses: [{ weight_us: .001 }] },
  });
  expect(await screen.findByText(/без обратного влияния цели на сеть/)).toBeInTheDocument();
});

test('rejects a submitted run belonging to another source instead of displaying its result', async () => {
  simulationApi.populationTargetRuns.mockResolvedValue({ items: [] });
  simulationApi.preparePopulationTarget.mockResolvedValue({ source_ids: [10], graph_manifest_sha256: 'a',
    sha256: 'b', manifest_sha256: 'c', duration_ms: 200 });
  simulationApi.createPopulationTarget.mockResolvedValue({ id: 'other', parent_run_id: 'wrong',
    configuration: { target_id: 20 }, state: 'completed', result: { preview: { neural_uv: [1, 2] } } });
  render(<PopulationTargetReplay runId="source" nodeId="20" candidates={[{ source_id: 10, events: 2 }]} />);
  fireEvent.click(screen.getByText('Рассчитать ответ нейрона'));
  await waitFor(() => expect(screen.getByRole('checkbox', { name: /10 · событий: 2/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('checkbox', { name: /10 · событий: 2/ }));
  for (const [label, value] of [['Задержка, мс', '1'], ['Проводимость, мкСм', '.001'],
    ['Нарастание, мс', '.2'], ['Спад, мс', '2'], ['Потенциал реверсии, мВ', '0'],
    ['Допуск геометрии, мкм', '2']]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось запустить расчёт.');
  expect(screen.queryByText('Состояние: завершён')).not.toBeInTheDocument();
});

test('restores a saved target and offers it to the shared timeline', async () => {
  const target = { id: 'target', parent_run_id: 'source', state: 'completed', configuration: { target_id: 20 },
    result: { preview: { source_cells: 1, target_id: 20, time_ms: [0, 1], neural_uv: [0, 1] } } };
  const show = jest.fn();
  simulationApi.populationTargetRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed' }, { id: 'target', state: 'completed' }] });
  simulationApi.get.mockResolvedValue(target);
  render(<PopulationTargetReplay runId="source" nodeId="20" candidates={[{ source_id: 10, events: 2 }]} onShowOnTimeline={show} />);
  fireEvent.click(screen.getByText('Рассчитать ответ нейрона'));
  fireEvent.click(await screen.findByRole('button', { name: 'Показать на общей шкале' }));
  expect(show).toHaveBeenCalledWith(target);
  expect(simulationApi.get).toHaveBeenCalledWith('target', expect.any(AbortSignal));
});

test('switches between saved runs without mixing their source or target', async () => {
  const make = (id, timing_mode, target_id = 20) => ({ id, parent_run_id: 'source', state: 'completed',
    configuration: { target_id, timing_mode }, result: { preview: { source_cells: 1, target_id,
      time_ms: [0, 1], neural_uv: [0, 1], timing_mode } } });
  const lower = make('lower', 'lower_bound'), upper = make('upper', 'upper_bound');
  simulationApi.populationTargetRuns.mockResolvedValue({ items: [lower, upper] });
  simulationApi.get.mockImplementation(async id => id === 'lower' ? lower : upper);
  render(<PopulationTargetReplay runId="source" nodeId="20" candidates={[{ source_id: 10, events: 2 }]} />);
  fireEvent.click(screen.getByText('Рассчитать ответ нейрона'));
  expect(await screen.findByText('Время событий: нижняя граница интервала.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Сохранённый расчёт'), { target: { value: 'upper' } });
  expect(await screen.findByText('Время событий: верхняя граница интервала.')).toBeInTheDocument();
  simulationApi.get.mockResolvedValue(make('lower', 'lower_bound', 21));
  fireEvent.change(screen.getByLabelText('Сохранённый расчёт'), { target: { value: 'lower' } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось открыть выбранный расчёт.');
  expect(screen.getByText('Время событий: верхняя граница интервала.')).toBeInTheDocument();
});

test('keeps submission locked if stored runs cannot be checked, then retries', async () => {
  simulationApi.populationTargetRuns.mockReset().mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({ items: [] });
  render(<PopulationTargetReplay runId="source" nodeId="20" candidates={[{ source_id: 10, events: 2 }]} />);
  fireEvent.click(screen.getByText('Рассчитать ответ нейрона'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить сохранённые расчёты.');
  expect(screen.getByRole('checkbox', { name: /10 · событий: 2/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
  await waitFor(() => expect(screen.getByRole('checkbox', { name: /10 · событий: 2/ })).toBeEnabled());
});
