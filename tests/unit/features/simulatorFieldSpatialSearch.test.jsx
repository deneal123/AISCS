import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FieldSpatialSearch from '../../../src/features/simulator/field/FieldSpatialSearch';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { spatialCandidates: jest.fn() } }));
beforeEach(() => jest.resetAllMocks());
const simulation = { source_um: [1, 2, 3], return_um: [4, 5, 6], electrode_um: [7, 8, 9], reference_um: [10, 11, 12] };
const candidate = { body_id: 10, child_node_id: 4, distance_um: 12.3, contact: 0, isolated_root: false, edge_fraction: .75,
  conservative_clearance_um: [12.2, 30], recording_clearance_um: [20, 30],
  geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } };

test('adds an explicitly chosen geometry candidate', async () => {
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate] });
  const add = jest.fn();
  render(<FieldSpatialSearch sceneRunId="run" simulation={simulation} sources={[]} replay={[]} onAdd={add} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByText(/ID 10 · 12,3|ID 10 · 12\.3/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Добавить' }));
  expect(add).toHaveBeenCalledWith(candidate);
});

test('unavailable index reports status and retries', async () => {
  simulationApi.spatialCandidates.mockRejectedValueOnce({ status: 503 }).mockResolvedValueOnce({ candidates: [] });
  render(<FieldSpatialSearch sceneRunId="run" simulation={simulation} sources={[]} replay={[]} onAdd={() => {}} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('индекс ещё не готов');
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  await waitFor(() => expect(screen.getByText(/Найдено: 0/)).toBeInTheDocument());
});

test('explains when another search is still running', async () => {
  simulationApi.spatialCandidates.mockRejectedValue({ status: 429 });
  render(<FieldSpatialSearch sceneRunId="run" simulation={simulation} sources={[]} replay={[]} onAdd={() => {}} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Другой поиск ещё выполняется');
});

test('explains when the selected run has no compatible verified graph', async () => {
  simulationApi.spatialCandidates.mockRejectedValue({ status: 409 });
  render(<FieldSpatialSearch sceneRunId="old-run" simulation={simulation} sources={[]} replay={[]} onAdd={() => {}} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Выберите завершённый опыт');
});

test('moving STIM cancels the stale search', async () => {
  let resolve;
  simulationApi.spatialCandidates.mockImplementation(() => new Promise(done => { resolve = done; }));
  const props = { sceneRunId: 'run', simulation, sources: [], replay: [], onAdd: () => {} };
  const { rerender } = render(<FieldSpatialSearch {...props} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  const signal = simulationApi.spatialCandidates.mock.calls[0][2];
  rerender(<FieldSpatialSearch {...props} simulation={{ ...simulation, source_um: [2, 2, 3] }} />);
  expect(signal.aborted).toBe(true);
  resolve({ candidates: [candidate] });
  await waitFor(() => expect(screen.queryByText(/ID 10/)).not.toBeInTheDocument());
});

test('disables a candidate with unsupported SWC geometry', async () => {
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [{ ...candidate,
    geometry: { ...candidate.geometry, zero_length_edges: 1 } }] });
  render(<FieldSpatialSearch sceneRunId="run" simulation={simulation} sources={[]} replay={[]} onAdd={() => {}} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByText(/геометрия не поддерживается/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled();
});

test('does not add a source whose centerline is inside the clearance', async () => {
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [{ ...candidate, distance_um: .5, conservative_clearance_um: [.4, 30] }] });
  render(<FieldSpatialSearch sceneRunId="run" simulation={{ ...simulation, clearance_um: 1 }}
    sources={[]} replay={[]} onAdd={() => {}} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByText(/STIM внутри зазора/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled();
});

test('rejects candidates with missing or insufficient E1 and REF clearance', async () => {
  const rows = [{ ...candidate, recording_clearance_um: [.5, 30] },
    { ...candidate, body_id: 11, recording_clearance_um: null }];
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  render(<FieldSpatialSearch sceneRunId="run" simulation={{ ...simulation, clearance_um: 1 }}
    sources={[]} replay={[]} onAdd={() => {}} onReplaceMany={() => {}} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByText(/E1 или REF внутри зазора/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Заменить источники найденными (0)' })).toBeDisabled();
});

test('moving a recording contact cancels an obsolete search', async () => {
  simulationApi.spatialCandidates.mockImplementation(() => new Promise(() => {}));
  const props = { sceneRunId: 'run', simulation, sources: [], replay: [], onAdd: () => {} };
  const { rerender } = render(<FieldSpatialSearch {...props} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  const signal = simulationApi.spatialCandidates.mock.calls[0][2];
  rerender(<FieldSpatialSearch {...props} simulation={{ ...simulation, electrode_um: [20, 8, 9] }} />);
  expect(signal.aborted).toBe(true);
});

test('bulk-add includes only available candidates on the current page', async () => {
  const rows = Array.from({ length: 52 }, (_, i) => ({ ...candidate, body_id: 100 + i }));
  rows[1] = { ...rows[1], geometry: { ...candidate.geometry, zero_length_edges: 1 } };
  rows[2] = { ...rows[2], conservative_clearance_um: [.5, 30] };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  const addMany = jest.fn();
  render(<FieldSpatialSearch sceneRunId="run" simulation={{ ...simulation, clearance_um: 1 }}
    sources={[{ body_id: 103 }]} replay={[104]} onAdd={() => {}} onAddMany={addMany} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  const batch = await screen.findByRole('button', { name: 'Добавить подходящие на странице (46)' });
  fireEvent.click(batch);
  expect(addMany).toHaveBeenCalledWith(rows.filter((row, i) => i < 50 && ![1, 2, 3, 4].includes(i)));
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
  fireEvent.click(screen.getByRole('button', { name: 'Добавить подходящие на странице (2)' }));
  expect(addMany).toHaveBeenLastCalledWith(rows.slice(50));
});

test('adds eligible cells across pages while excluding incompatible and occupied cells', async () => {
  const rows = Array.from({ length: 53 }, (_, i) => ({ ...candidate, body_id: 100 + i }));
  rows[51] = { ...rows[51], geometry: { ...candidate.geometry, zero_length_edges: 1 } };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  const addMany = jest.fn();
  render(<FieldSpatialSearch sceneRunId="run" simulation={{ ...simulation, clearance_um: 1 }}
    sources={[{ body_id: 100 }]} replay={[101]} onAdd={() => {}} onAddMany={addMany} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Добавить все подходящие (50)' }));
  expect(addMany).toHaveBeenCalledWith(rows.filter((row, i) => ![0, 1, 51].includes(i)));
});

test('explains when a batch exceeds the supported request size', async () => {
  const rows = Array.from({ length: 51 }, (_, i) => ({ ...candidate, body_id: 100 + i }));
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  render(<FieldSpatialSearch sceneRunId="run" simulation={simulation} sources={[]} replay={[]}
    onAdd={() => {}} onAddMany={() => {}} canAddMany={items => items.length < 51} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByRole('button', { name: 'Добавить все подходящие (51)' })).toBeDisabled();
  expect(screen.getByText(/не помещаются в запрос/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Добавить подходящие на странице (50)' })).toBeEnabled();
});

test('replacement includes prior sources but never replaces recording cells or unsafe geometry', async () => {
  const rows = [candidate, { ...candidate, body_id: 11 }, { ...candidate, body_id: 12 },
    { ...candidate, body_id: 13, geometry: { ...candidate.geometry, zero_length_edges: 1 } },
    { ...candidate, body_id: 14, conservative_clearance_um: null }];
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  const replace = jest.fn();
  render(<FieldSpatialSearch sceneRunId="run" simulation={{ ...simulation, clearance_um: 1 }}
    sources={[{ body_id: 10 }]} replay={[11]} onAdd={() => {}} onReplaceMany={replace} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Заменить источники найденными (2)' }));
  expect(replace).toHaveBeenCalledWith([rows[0], rows[2]]);
});

test('does not silently truncate replacement that exceeds request size', async () => {
  const rows = [candidate, { ...candidate, body_id: 11 }];
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  render(<FieldSpatialSearch sceneRunId="run" simulation={simulation} sources={[]} replay={[]}
    onAdd={() => {}} onReplaceMany={() => {}} canReplaceMany={() => false} />);
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByRole('button', { name: 'Заменить источники найденными (2)' })).toBeDisabled();
  expect(screen.getByText(/Уменьшите радиус поиска/)).toBeInTheDocument();
});
