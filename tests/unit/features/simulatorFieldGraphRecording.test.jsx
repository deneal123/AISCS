import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import FieldGraphRecording, { fieldConfigurationFits, sourceFromCandidate } from '../../../src/features/simulator/field/FieldGraphRecording';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { fieldGraphRuns: jest.fn(), get: jest.fn(), createFieldGraph: jest.fn(), spatialCandidates: jest.fn(), contactScreen: jest.fn(), contactPositions: jest.fn() } }));
jest.mock('../../../src/features/simulator/recording/SignalPlot', () => ({ preview }) => <div>Трасса: {preview.signal_uv.length}<span data-testid="signal-values">{preview.signal_uv.join(',')}</span></div>);
jest.mock('../../../src/features/simulator/field/FieldContactScene', () => ({ onChange }) => <button type="button" onClick={() => onChange('source_um', [21, 22, 23])}>Переместить контакт</button>);
jest.mock('../../../src/features/simulator/field/FieldNetworkScene', () => () => <div>События графа</div>);

beforeEach(() => jest.resetAllMocks());

test('opens an explicitly selected earlier completed electrical calculation', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [
    { id: 'newer', state: 'completed', title: 'Новый' },
    { id: 'older', state: 'completed', title: 'Ранее' },
  ] });
  simulationApi.get.mockImplementation(async id => ({ id, state: 'completed',
    result: { preview: { time_ms: [0, 1], neural_uv: [0, 0], source_cells: 1, replay_cells: 1 } } }));
  render(<FieldGraphRecording />);
  const select = await screen.findByLabelText('Завершённый электрический расчёт');
  await waitFor(() => expect(select).toHaveValue('newer'));
  fireEvent.change(select, { target: { value: 'older' } });
  await waitFor(() => expect(select).toHaveValue('older'));
  expect(simulationApi.get).toHaveBeenCalledWith('older', expect.anything());
});

test('explains unavailable contact screening without presenting a result', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error: 'executor_contact_screen_unavailable' }] });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Данные для проверки положения контактов недоступны');
  expect(simulationApi.get).not.toHaveBeenCalled();
});

test('warns about possible events outside the sampled compartment without asserting spikes', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 0], source_cells: 1, replay_cells: 1,
    source_all_compartments_voltage_range_mv: { minimum: -70, maximum: 10 },
    source_unobserved_threshold_candidates: 1,
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByText(/Возможный пропуск:/)).toHaveTextContent('возбуждение не подтверждено');
});

test('distinguishes earlier compartment threshold crossings from confirmed spikes', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 0], source_cells: 2, replay_cells: 1,
    source_compartment_crossings: { sources_checked: 2, outside_selected_only: 0,
      earlier_than_selected: 1, initial_above_sources: 0 },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByText(/раньше его события — 1/)).toHaveTextContent('не подтверждают спайки');
});

test('warns when saved compartment samples occupy bins absent from the selected trace', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 0], source_cells: 2, replay_cells: 1,
    compartment_bin_coverage: { sources_checked: 2, sources_with_unrepresented_bins: 1,
      unrepresented_source_bins: 2 },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByText(/Они не переданы в граф/)).toHaveTextContent('не подтверждает отдельные спайки');
});

test('uses measured compartment crossings instead of duplicating the maximum-only warning', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 0], source_cells: 1, replay_cells: 1,
    source_unobserved_threshold_candidates: 1,
    source_compartment_crossings: { sources_checked: 1, outside_selected_only: 1,
      earlier_than_selected: 0, initial_above_sources: 0 },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByText(/без его события — 1/)).toBeInTheDocument();
  expect(screen.queryByText(/Возможный пропуск:/)).not.toBeInTheDocument();
});

test('limits batch configuration before the backend request limit', () => {
  expect(fieldConfigurationFits({ source_cells: [{ body_id: 1 }] })).toBe(true);
  expect(fieldConfigurationFits({ source_cells: Array.from({ length: 1000 }, (_, i) => ({ body_id: i + 1, child_node_id: i + 2, threshold_mv: -20 })) })).toBe(false);
  expect(fieldConfigurationFits({ label: 'я'.repeat(4000) })).toBe(false);
});

test('preserves the checked SWC digest in a source selected by spatial search', () => {
  const source = sourceFromCandidate({ body_id: 10, child_node_id: 8, edge_fraction: .5, source_sha256: 'a'.repeat(64) });
  expect(source.morphology_sha256).toBe('a'.repeat(64));
});

test('only offers body playback for the matching registered graph', async () => {
  const manifest = 'a'.repeat(64);
  const selected = { id: 'result', configuration: { graph_manifest_sha256: manifest, simulation: {} }, result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1,
  } } };
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue(selected);
  const onShowOnBody = jest.fn();
  const { rerender } = render(<FieldGraphRecording sceneRunId="scene" sceneManifest="b" sceneDescription={{}} onShowOnBody={onShowOnBody} />);
  expect(await screen.findByText(/электрическая стимуляция/i)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Показать события на модели мухи' })).not.toBeInTheDocument();
  rerender(<FieldGraphRecording sceneRunId="scene" sceneManifest={manifest} sceneDescription={{}} onShowOnBody={onShowOnBody} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Показать события на модели мухи' }));
  expect(onShowOnBody).toHaveBeenCalledWith(selected);
});

test('body contact draft is applied to the matching saved electrical run only', async () => {
  const manifest = 'a'.repeat(64);
  const simulation = { source_um: [1, 2, 3], return_um: [100, 2, 3], electrode_um: [2, 50, 3],
    reference_um: [100, 50, 3], current_na: 1, conductivity_s_m: .3, clearance_um: 1,
    nseg_per_edge: 1, duration_ms: 10, dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3,
    rise_time_ms: .2, interphase_gap_ms: 0, pulse_shape: 'monophasic' };
  const selected = { id: 'saved', state: 'completed', configuration: { graph_manifest_sha256: manifest,
    source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }], replay_ids: [3], simulation },
    result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } };
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'newer', state: 'completed' }, { id: 'saved', state: 'completed' }] });
  simulationApi.get.mockResolvedValue(selected);
  const consume = jest.fn();
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={manifest} sceneDescription={{}}
    incomingContacts={{ fieldRunId: 'saved', simulation: { ...simulation, source_um: [9, 8, 7] } }} onConsumeContacts={consume} />);
  expect(await screen.findByLabelText('STIM+ X, мкм')).toHaveValue(9);
  expect(screen.getByLabelText('STIM+ Y, мкм')).toHaveValue(8);
  expect(simulationApi.get).toHaveBeenCalledWith('saved', expect.anything());
  expect(consume).toHaveBeenCalled();
});

test('replaces the old source population using the screened results while retaining recording cells', async () => {
  const manifest = 'a'.repeat(64);
  const simulation = { source_um: [1, 2, 3], return_um: [100, 2, 3], electrode_um: [2, 50, 3],
    reference_um: [100, 50, 3], current_na: 1, conductivity_s_m: .3, clearance_um: 1,
    nseg_per_edge: 1, duration_ms: 10, dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3,
    rise_time_ms: .2, interphase_gap_ms: 0, pulse_shape: 'monophasic' };
  const selected = { id: 'saved', state: 'completed', configuration: { graph_manifest_sha256: manifest,
    source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }], replay_ids: [3], simulation },
    result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } };
  const row = { body_id: 8, child_node_id: 9, edge_fraction: .75, distance_um: 5, contact: 0,
    isolated_root: false, conservative_clearance_um: [4, 10], recording_clearance_um: [20, 30],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } };
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  simulationApi.get.mockResolvedValue(selected);
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [row] });
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={manifest} sceneDescription={{}}
    incomingContacts={{ fieldRunId: 'saved', simulation }} onConsumeContacts={() => {}} />);
  fireEvent.click(await screen.findByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Заменить источники найденными (1)' }));
  fireEvent.click(screen.getByText(/Клетки модели/));
  expect(screen.getByLabelText('ID источника 1')).toHaveValue(8);
  expect(screen.getByLabelText('Вершина SWC 1')).toHaveValue(9);
  expect(screen.getByLabelText('ID клетки записи 1')).toHaveValue(3);
  fireEvent.change(screen.getByLabelText('STIM+ X, мкм'), { target: { value: '20' } });
  expect(screen.getByRole('alert')).toHaveTextContent('Контакты изменились после выбора клеток');
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Заменить источники найденными (1)' }));
  expect(screen.queryByText(/Контакты изменились после выбора клеток/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeEnabled();
  fireEvent.change(screen.getByLabelText('STIM+ X, мкм'), { target: { value: '21' } });
  fireEvent.click(screen.getByRole('button', { name: 'Оставить прежний состав клеток' }));
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeEnabled();
  fireEvent.change(screen.getByLabelText('STIM+ X, мкм'), { target: { value: '22' } });
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeDisabled();
});
const timingDefaults = { duration_ms: 10, dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3,
  rise_time_ms: .2, interphase_gap_ms: 0, pulse_shape: 'monophasic', conductivity_s_m: .3 };

test('shows independent recording and accurately timed saturation intervals', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', configuration: { simulation: { current_na: 0 } }, result: { preview: {
    time_ms: [0, 1, 2], neural_uv: [0, 1, 2], stimulus_fraction: [0, 1, 0], source_cells: 1, replay_cells: 1, network_spikes_by_ms: [0, 2, 1],
    acquisition: { valid_samples: [true, false, false], saturated_samples: [false, true, false],
      mask_intervals: [{ start_ms: 0, end_ms: .5, valid: true, saturated: false },
        { start_ms: .5, end_ms: 2, valid: false, saturated: true }] },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByText(/обнаружено насыщение/)).toBeInTheDocument();
  expect(screen.getByText(/не привязаны к текущей сцене/)).toBeInTheDocument();
  expect(screen.getByText(/не запись всей сети/)).toBeInTheDocument();
  expect(screen.getByText('Ток STIM = форма импульса × 0 нА.')).toBeInTheDocument();
  expect(screen.getByText('Трасса: 3')).toBeInTheDocument();
  expect(screen.getByText('События модели сети · 3 · шаг 1 мс')).toBeInTheDocument();
  const mask = screen.getByRole('img', { name: /Маска обработки/ });
  expect(screen.getByText(/Отсутствие маски не подтверждает точность сигнала/)).toBeInTheDocument();
  expect(mask.querySelectorAll('rect')[1]).toHaveAttribute('x', '0.5');
  expect(mask.querySelectorAll('rect')[1]).toHaveAttribute('width', '1.5');
  fireEvent.keyDown(screen.getByRole('slider', { name: 'Время на шкале стимула' }), { key: 'End' });
  expect(mask.querySelector('[data-role="cursor"]')).toHaveAttribute('x1', '2');
  expect(screen.getByRole('img', { name: /События сетевой модели/ }).querySelector('[data-role="cursor"]'))
    .toHaveAttribute('x1', '2');
});

test('switches between neural, raw artifact and acquisition traces', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [1, 2], total_uv: [5, 6], source_cells: 1, replay_cells: 1,
    acquisition: { filtered_total_uv: [3, 4], valid_samples: [true, false], saturated_samples: [false, true],
      mask_intervals: [{ start_ms: 0, end_ms: 1, valid: false, saturated: true }] },
  } } });
  render(<FieldGraphRecording />);
  await screen.findByText(/Расчётный нейронный компонент/);
  expect(screen.getByTestId('signal-values')).toHaveTextContent('1,2');
  fireEvent.click(screen.getByRole('button', { name: 'С артефактом' }));
  expect(screen.getByText((_, node) => node.tagName === 'P' && node.textContent.includes('Сумма нейронного компонента'))).toBeInTheDocument();
  expect(screen.getByTestId('signal-values')).toHaveTextContent('5,6');
  fireEvent.click(screen.getByRole('button', { name: 'Модель регистрации' }));
  expect(screen.getByText((_, node) => node.tagName === 'P' && node.textContent.includes('Результат модельного фильтра'))).toBeInTheDocument();
  expect(screen.getByTestId('signal-values')).toHaveTextContent('3,4');
});

test('retains the last completed result and marks a later failure', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [
    { id: 'failed', state: 'failed' }, { id: 'previous', state: 'completed' },
  ] });
  simulationApi.get.mockResolvedValue({ id: 'previous', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1,
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByText(/последний завершился ошибкой/)).toBeInTheDocument();
});

test('explains a contact-clearance failure without exposing raw executor errors', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [
    { id: 'failed', state: 'failed', error: 'executor_contact_clearance' },
    { id: 'previous', state: 'completed' },
  ] });
  simulationApi.get.mockResolvedValue({ id: 'previous', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1,
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Контакт слишком близок к восстановленному отростку');
  expect(screen.getByText(/последний завершился ошибкой/)).toBeInTheDocument();
});

test('explains that a changed morphology requires a fresh source selection', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [
    { id: 'failed', state: 'failed', error: 'executor_morphology_changed' },
  ] });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Морфология выбранной клетки изменилась');
});

test('flags extreme sampled compartment voltages without claiming biological calibration', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1,
    source_voltage_range_mv: { minimum: -17000, maximum: -63.4 },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('alert')).toHaveTextContent('не является биологической калибровкой');
  expect(screen.getByText(/−17000|−17000.0|-17000.0/)).toBeInTheDocument();
});

test('flags extreme voltage in other source compartments', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1,
    source_voltage_range_mv: { minimum: -70, maximum: -60 },
    source_all_compartments_voltage_range_mv: { minimum: -500, maximum: 20 },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('alert')).toHaveTextContent('не является биологической калибровкой');
  expect(screen.getByText(/Диапазон всех компартментов источников/)).toHaveTextContent('-500.0');
});

test('flags extreme voltage in a replay cell', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', result: { preview: {
    time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1,
    source_voltage_range_mv: { minimum: -70, maximum: -60 },
    replay_all_compartments_voltage_range_mv: { minimum: -500, maximum: 30 },
  } } });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('alert')).toHaveTextContent('не является биологической калибровкой');
  expect(screen.getByText(/Диапазон компартментов клеток записи/)).toHaveTextContent('-500.0');
});

test('allows retry after a loading error', async () => {
  simulationApi.fieldGraphRuns.mockRejectedValueOnce(new Error()).mockResolvedValueOnce({ items: [] });
  render(<FieldGraphRecording />);
  expect(await screen.findByRole('status')).toHaveTextContent('Не удалось обновить');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Повторить' })); });
  expect(simulationApi.fieldGraphRuns).toHaveBeenCalledTimes(2);
});

test('does not search a scene with a different connectome revision', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', configuration: {
    graph_manifest_sha256: 'a'.repeat(64), source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }],
    replay_ids: [3], simulation: { source_um: [0, 0, 0], return_um: [100, 0, 0], electrode_um: [0, 50, 0],
      reference_um: [100, 50, 0], current_na: 1000, clearance_um: 1, nseg_per_edge: 1, ...timingDefaults },
  }, result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } });
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={'b'.repeat(64)} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Изменить контакты и рассчитать' }));
  expect(screen.getByText(/с той же версией графа/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  expect(screen.getByRole('button', { name: 'Найти' })).toBeDisabled();
});

test('reuses request id after uncertain submission and keeps edited coordinates', async () => {
  Object.defineProperty(global, 'crypto', { configurable: true, value: { randomUUID: () => '3b0f5bb3-983b-4874-9907-d3858393eb42' } });
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', configuration: { source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }], replay_ids: [3], simulation: {
    source_um: [0, 0, 0], return_um: [100, 0, 0], electrode_um: [0, 50, 0],
    reference_um: [100, 50, 0], current_na: 1000, clearance_um: 1, nseg_per_edge: 1, ...timingDefaults,
  } }, result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } });
  simulationApi.createFieldGraph.mockRejectedValueOnce(new Error()).mockResolvedValueOnce({ id: 'new' });
  render(<FieldGraphRecording />);
  fireEvent.click(await screen.findByRole('button', { name: 'Изменить контакты и рассчитать' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Сохранить токи для быстрого изменения E1 и REF' }));
  fireEvent.change(screen.getByLabelText('STIM+ X, мкм'), { target: { value: '20' } });
  fireEvent.click(screen.getByRole('button', { name: 'Оставить прежний состав клеток' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Запустить расчёт' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить отправку');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Повторить отправку' })); });
  expect(simulationApi.createFieldGraph).toHaveBeenCalledTimes(2);
  const [first, second] = simulationApi.createFieldGraph.mock.calls.map(([payload]) => payload);
  expect(first.request_id).toBe(second.request_id);
  expect(first.configuration.retain_currents).toBe(true);
  expect(first.configuration.simulation.source_um[0]).toBe(20);
});

test('distinguishes rejected parameters from an uncertain submission', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', configuration: { source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }], replay_ids: [3], simulation: {
    source_um: [0, 0, 0], return_um: [100, 0, 0], electrode_um: [0, 50, 0],
    reference_um: [100, 50, 0], current_na: 1000, clearance_um: 1, nseg_per_edge: 1, ...timingDefaults,
  } }, result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } });
  simulationApi.createFieldGraph.mockRejectedValueOnce({ status: 422 });
  render(<FieldGraphRecording />);
  fireEvent.click(await screen.findByRole('button', { name: 'Изменить контакты и рассчитать' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Запустить расчёт' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Параметры не прошли проверку');
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('STIM+ X, мкм'), { target: { value: '20' } });
  fireEvent.click(screen.getByRole('button', { name: 'Оставить прежний состав клеток' }));
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeEnabled();
});

test('a scene move updates the submitted native coordinates', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', configuration: { source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }], replay_ids: [3], simulation: {
    source_um: [0, 0, 0], return_um: [100, 0, 0], electrode_um: [0, 50, 0],
    reference_um: [100, 50, 0], current_na: 1000, clearance_um: 1, nseg_per_edge: 1, ...timingDefaults,
  } }, result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } });
  simulationApi.createFieldGraph.mockResolvedValue({ id: 'new' });
  render(<FieldGraphRecording />);
  fireEvent.click(await screen.findByRole('button', { name: 'Изменить контакты и рассчитать' }));
  fireEvent.change(screen.getByLabelText('Компартментов на сегмент'), { target: { value: '2' } });
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Компартментов на сегмент'), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: 'Переместить контакт' }));
  expect(screen.getByLabelText('STIM+ X, мкм')).toHaveValue(21);
  fireEvent.click(screen.getByRole('button', { name: 'Оставить прежний состав клеток' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Запустить расчёт' })); });
  expect(simulationApi.createFieldGraph.mock.calls[0][0].configuration.simulation.source_um).toEqual([21, 22, 23]);
  expect(simulationApi.createFieldGraph.mock.calls[0][0].configuration.simulation.nseg_per_edge).toBe(3);
});

test('a checked alternative updates the submitted STIM coordinates', async () => {
  const manifest = 'a'.repeat(64);
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [{ id: 'result', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'result', configuration: {
    graph_manifest_sha256: manifest, source_cells: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }],
    replay_ids: [3], simulation: { source_um: [0, 0, 0], return_um: [100, 0, 0],
      electrode_um: [0, 50, 0], reference_um: [100, 50, 0], current_na: 1000,
      clearance_um: 1, nseg_per_edge: 1, ...timingDefaults },
  }, result: { preview: { time_ms: [0, 1], neural_uv: [0, 1], source_cells: 1, replay_cells: 1 } } });
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ body_id: 1, contact_indices: [0] }] });
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [{ contact_indices: [1, 2, 3, 4, 5] }] });
  simulationApi.createFieldGraph.mockResolvedValue({ id: 'new' });
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={manifest} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Изменить контакты и рассчитать' }));
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  await screen.findByText(/Возможное пересечение/);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить соседние точки' }));
  fireEvent.click(await screen.findByRole('button', { name: '-25 / 0 / 0' }));
  expect(screen.getByLabelText('STIM+ X, мкм')).toHaveValue(-25);
  fireEvent.click(screen.getByRole('button', { name: 'Оставить прежний состав клеток' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Запустить расчёт' })); });
  expect(simulationApi.createFieldGraph.mock.calls[0][0].configuration.simulation.source_um).toEqual([-25, 0, 0]);
});

test('a compatible graph enables a first explicitly labelled engineering example', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [] });
  simulationApi.createFieldGraph.mockResolvedValue({ id: 'first' });
  const manifest = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={manifest} />);
  expect(await screen.findByText(/условные параметры и демонстрационный ток/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Настроить первый расчёт' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Запустить расчёт' })); });
  const sent = simulationApi.createFieldGraph.mock.calls[0][0].configuration;
  expect(sent.graph_manifest_sha256).toBe(manifest);
  expect(sent.source_cells[0].body_id).toBe(14110);
  expect(sent.replay_ids).toEqual([324531]);
  expect(sent.simulation.current_na).toBe(-300);
});

test('the example is unavailable for an unverified graph revision', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [] });
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={'a'.repeat(64)} />);
  expect(await screen.findByRole('button', { name: 'Настроить первый расчёт' })).toBeDisabled();
});

test('submits an explicitly configured two-pulse train', async () => {
  simulationApi.fieldGraphRuns.mockResolvedValue({ items: [] });
  simulationApi.createFieldGraph.mockResolvedValue({ id: 'train' });
  const manifest = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest={manifest} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Настроить первый расчёт' }));
  fireEvent.click(screen.getByText('Параметры электрического импульса'));
  fireEvent.change(screen.getByLabelText('Количество импульсов'), { target: { value: '2' } });
  expect(screen.getByRole('button', { name: 'Запустить расчёт' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Интервал между началами, мс'), { target: { value: '5' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Сохранить разность состояний сети' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Запустить расчёт' })); });
  expect(simulationApi.createFieldGraph.mock.calls[0][0].configuration.simulation).toMatchObject({
    pulse_count: 2, pulse_interval_ms: 5,
  });
  expect(simulationApi.createFieldGraph.mock.calls[0][0].configuration.retain_state_contrast).toBe(true);
});

test('an older backend is identified and cannot start the example', async () => {
  simulationApi.fieldGraphRuns.mockRejectedValue({ status: 404 });
  render(<FieldGraphRecording sceneRunId="scene" sceneManifest="742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2" />);
  expect(await screen.findByText(/версия backend не поддерживает/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Настроить первый расчёт' })).toBeDisabled();
});
