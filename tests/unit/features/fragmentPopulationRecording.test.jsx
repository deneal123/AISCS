import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Recording from '../../../src/features/simulator/recording/FragmentPopulationRecording';
import { simulationApi } from '../../../src/features/simulator/api';
import { fieldDemoPreset } from '../../../src/features/simulator/field/fieldDemoPreset';
import useWholeNetworkProxy from '../../../src/features/simulator/recording/useWholeNetworkProxy';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  fragmentPopulationRuns: jest.fn(), createFragmentPopulation: jest.fn(), get: jest.fn(),
  feedbackRuns: jest.fn(), feedbackSource: jest.fn(), createFeedback: jest.fn(),
  cancel: jest.fn(), artifacts: jest.fn(), download: jest.fn(), spatialCandidates: jest.fn(), contactScreen: jest.fn(), contactPositions: jest.fn(),
} }));
jest.mock('../../../src/features/simulator/recording/SignalPlot', () => ({ preview }) => <div>Сигнал: {preview.signal_uv.length}</div>);
jest.mock('../../../src/features/simulator/recording/useWholeNetworkProxy', () => jest.fn());

// Mirror the single launch control owned by SimulatorPage.
function FragmentPopulationRecording({ formRef, onPrimaryStatus, ...props }) {
  const ownForm = React.useRef(null);
  const [ready, setReady] = React.useState(false);
  const report = React.useCallback(status => {
    setReady(status.ready);
    onPrimaryStatus?.(status);
  }, [onPrimaryStatus]);
  const form = formRef || ownForm;
  return <><Recording {...props} formRef={form} onPrimaryStatus={report} />
    <button type="button" disabled={!ready} onClick={() => fireEvent.submit(form.current)}>Рассчитать</button></>;
}

const graph = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
const coupledRun = parent => ({ id: 'coupled', parent_run_id: parent, state: 'completed',
  configuration: { graph_manifest_sha256: graph }, result: {
    manifest: { files: [{ name: 'coupled-events.bin' }, { name: 'coupled-delta.bin' }] },
    preview: { status: 'converged', timeline: { time_ms: [0, 1], neural_uv: [0, 0] } },
  } });
beforeEach(() => { sessionStorage.clear(); jest.resetAllMocks(); useWholeNetworkProxy.mockReturnValue({ status: 'unavailable', run: null }); global.crypto = { randomUUID: () => 'fba50b24-f408-4d70-bd9b-3f0e18f76412' }; simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [] }); simulationApi.feedbackRuns.mockResolvedValue({ items: [] }); simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [] }); simulationApi.spatialCandidates.mockResolvedValue({ candidates: [1, 2].map(body_id => ({ body_id, child_node_id: 1, edge_fraction: .5, isolated_root: false, geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 }, conservative_clearance_um: [2, 2], recording_clearance_um: [2, 2] })) }); });

test('restores the last displayed source rather than the newest other source', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const newerId = '9b0d0d7e-6bfd-4bb8-ba5e-8d1535574ef5';
  sessionStorage.setItem(`simulation:selected-feedback-source:${sceneId}`, sourceId);
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [
    { id: newerId, state: 'completed' }, { id: sourceId, state: 'completed' },
  ] });
  simulationApi.get.mockResolvedValue({ id: sourceId, state: 'completed', configuration: {} });
  render(<Recording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.get).toHaveBeenCalledWith(sourceId, expect.any(AbortSignal)));
  expect(simulationApi.get).not.toHaveBeenCalledWith(newerId, expect.anything());
});

test('restores a selected source outside the first page without replacing it', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const newerId = '9b0d0d7e-6bfd-4bb8-ba5e-8d1535574ef5';
  sessionStorage.setItem(`simulation:selected-feedback-source:${sceneId}`, sourceId);
  simulationApi.fragmentPopulationRuns.mockResolvedValue({
    items: [{ id: newerId, state: 'completed' }], next_offset: 30,
  });
  simulationApi.get.mockResolvedValue({ id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1] } });
  render(<Recording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.feedbackRuns).toHaveBeenCalledWith(
    sourceId, expect.any(AbortSignal)));
  expect(simulationApi.get).not.toHaveBeenCalledWith(newerId, expect.anything());
});

test('rejects an out-of-page source belonging to another scene', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  sessionStorage.setItem(`simulation:selected-feedback-source:${sceneId}`, sourceId);
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [] });
  simulationApi.get.mockResolvedValue({ id: sourceId, parent_run_id: 'other', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1] } });
  render(<Recording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.get).toHaveBeenCalledWith(sourceId, expect.any(AbortSignal)));
  expect(simulationApi.feedbackRuns).not.toHaveBeenCalled();
});

test('exposes only current and search radius in the stimulation settings', async () => {
  render(<Recording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  expect(screen.getByLabelText('Ток STIM, нА')).toBeInTheDocument();
  expect(screen.getByLabelText('Радиус поиска, мкм')).toBeInTheDocument();
  expect(screen.queryByLabelText('ID клеток через запятую')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('STIM+ X')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Рассчитать' })).not.toBeInTheDocument();
});

test('automatically finds sources at the selected radius before the main launch', async () => {
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [{ body_id: 123, child_node_id: 4,
    edge_fraction: .5, isolated_root: false, geometry: { components: 1, isolated_roots: 0,
      zero_length_edges: 0, nonpositive_radius_edges: 0 }, conservative_clearance_um: [2, 2],
    recording_clearance_um: [2, 2] }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Радиус поиска, мкм'), { target: { value: '12' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates).toHaveBeenCalledWith('scene', expect.objectContaining({ radius_um: 12 }), expect.any(AbortSignal));
  expect(simulationApi.createFragmentPopulation).toHaveBeenCalledWith(expect.objectContaining({
    configuration: expect.objectContaining({ source_ids: [123] }),
  }));
});

test('reports contact screening and spatial search as distinct preparation stages', async () => {
  let finishScreen, finishSearch;
  const status = jest.fn();
  simulationApi.contactScreen.mockReturnValue(new Promise(resolve => { finishScreen = resolve; }));
  simulationApi.spatialCandidates.mockReturnValue(new Promise(resolve => { finishSearch = resolve; }));
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onPrimaryStatus={status} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ stage: 'Проверка контактов' })));
  await act(async () => { finishScreen({ potential_intersections: [] }); });
  await waitFor(() => expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ stage: 'Поиск нейронов · попытка 1 из 8' })));
  await act(async () => { status.mock.calls.at(-1)[0].cancel(); finishSearch({ candidates: [] }); });
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('does not automatically move operator contacts when screening detects an intersection', async () => {
  const adjust = jest.fn();
  simulationApi.contactScreen.mockResolvedValueOnce({ potential_intersections: [{ contact_indices: [0, 1, 2, 3] }] })
    .mockResolvedValueOnce({ potential_intersections: [] });
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onAdjustContact={adjust} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('STIM+, STIM−, E1, REF');
  expect(simulationApi.contactPositions).not.toHaveBeenCalled();
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
  expect(adjust).not.toHaveBeenCalled();
});

test('keeps operator contacts unchanged when no screened replacement is available', async () => {
  const adjust = jest.fn();
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ contact_indices: [0, 2] }] });
  simulationApi.contactPositions.mockImplementation(async (_id, request) => ({
    potential_intersections: [{ contact_indices: request.positions_um.map((_, index) => index) }],
  }));
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onAdjustContact={adjust} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('STIM+, E1');
  expect(simulationApi.contactPositions).not.toHaveBeenCalled();
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
  expect(adjust).not.toHaveBeenCalled();
});

test('forwards real source progress received over the run websocket', async () => {
  const originalSocket = global.WebSocket;
  let socket;
  global.WebSocket = class {
    constructor() { socket = this; }
    close() {}
  };
  simulationApi.eventsUrl = jest.fn(() => 'ws://localhost/test');
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`, JSON.stringify({
    version: 1, sourceId, requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e',
  }));
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'running' }] });
  const report = jest.fn();
  try {
    render(<Recording sceneRunId={sceneId} sceneManifest={graph} onPrimaryStatus={report} />);
    await waitFor(() => expect(socket).toBeDefined());
    act(() => socket.onmessage({ data: JSON.stringify({ event: { run_id: sourceId,
      progress: { phase: 'cells', done: 3, total: 10 } } }) }));
    expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ progress: {
      phase: 'cells', done: 3, total: 10, runId: sourceId,
    } }));
  } finally { global.WebSocket = originalSocket; }
});

test('stops contact preparation without submitting a run', async () => {
  let signal;
  simulationApi.contactScreen.mockImplementation((_scene, _request, abortSignal) => {
    signal = abortSignal;
    return new Promise((_resolve, reject) => abortSignal.addEventListener('abort', () => reject(new Error('aborted'))));
  });
  const report = jest.fn();
  const form = React.createRef();
  render(<Recording sceneRunId="scene" sceneManifest={graph} onPrimaryStatus={report} formRef={form} />);
  await act(async () => {});
  act(() => fireEvent.submit(form.current));
  await waitFor(() => expect(signal).toBeDefined());
  expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ canCancel: true }));
  await act(async () => { report.mock.lastCall[0].cancel(); });
  expect(signal.aborted).toBe(true);
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('resumes the feedback stage for the saved source after page reload', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const requestId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
  sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`,
    JSON.stringify({ version: 1, sourceId, requestId }));
  const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId ? source : { id, state: 'running' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'feedback', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1));
  expect(simulationApi.createFeedback.mock.calls[0][0]).toMatchObject({ request_id: requestId, parent_run_id: sourceId });
});

test('waits for the saved running source before resuming feedback', async () => {
  jest.useFakeTimers();
  try {
    const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
    const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
    const requestId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
    sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`,
      JSON.stringify({ version: 1, sourceId, requestId }));
    const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
      result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
    simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [{ id: sourceId, state: 'running' }] })
      .mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
    simulationApi.get.mockImplementation(async id => id === sourceId ? source : { id, state: 'running' });
    simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
      sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
    simulationApi.createFeedback.mockResolvedValue({ id: 'feedback', state: 'queued' });
    render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
    await act(async () => {});
    expect(simulationApi.createFeedback).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(10000); });
    expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1);
    expect(simulationApi.createFeedback.mock.calls[0][0].request_id).toBe(requestId);
  } finally { jest.useRealTimers(); }
});

test('does not resume a failed source after page reload', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const key = `simulation:pending-feedback:${sceneId}`;
  sessionStorage.setItem(key, JSON.stringify({ version: 1, sourceId,
    requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e' }));
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'failed' }] });
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
  expect(simulationApi.createFeedback).not.toHaveBeenCalled();
});

test('retains the resume receipt until the whole-network stage has ended', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const key = `simulation:pending-feedback:${sceneId}`;
  sessionStorage.setItem(key, JSON.stringify({ version: 1, sourceId,
    requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e' }));
  const source = { id: sourceId, state: 'completed', configuration: { graph_manifest_sha256: graph } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [source] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'coupled', state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupledRun(sourceId) : source);
  useWholeNetworkProxy.mockReturnValue({ status: 'loading', run: null });
  const view = render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(useWholeNetworkProxy).toHaveBeenCalledWith(expect.objectContaining({ id: sourceId }), true, true));
  expect(sessionStorage.getItem(key)).not.toBeNull();
  useWholeNetworkProxy.mockReturnValue({ status: 'completed', run: { id: 'proxy' } });
  view.rerender(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
});

test('retries failed network feedback without rerunning the saved physical source', async () => {
  const source = { id: 'saved', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === 'saved' ? source
    : id === 'failed' ? { id, state: 'failed' } : { id, state: 'running' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'retry', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить расчёт сети' }));
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1));
  expect(simulationApi.createFeedback.mock.calls[0][0].parent_run_id).toBe('saved');
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('reuses retry identity after an interrupted feedback submission', async () => {
  const uuid = jest.fn().mockReturnValueOnce('fba50b24-f408-4d70-bd9b-3f0e18f76412')
    .mockReturnValue('fba50b24-f408-4d70-bd9b-3f0e18f76413');
  global.crypto = { randomUUID: uuid };
  const source = { id: 'saved', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === 'saved' ? source
    : id === 'failed' ? { id, state: 'failed' } : { id, state: 'running' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockRejectedValueOnce(new Error('connection interrupted'))
    .mockResolvedValueOnce({ id: 'retry', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить расчёт сети' }));
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1));
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить расчёт сети' }));
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(2));
  expect(simulationApi.createFeedback.mock.calls[0][0].request_id)
    .toBe(simulationApi.createFeedback.mock.calls[1][0].request_id);
  expect(uuid).toHaveBeenCalledTimes(1);
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('restores an interrupted retry even when an older failed run exists', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const requestId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
  sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`,
    JSON.stringify({ version: 1, sourceId, requestId, retry: true }));
  const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'older', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId ? source : { id, state: 'running' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'retry', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1));
  expect(simulationApi.createFeedback.mock.calls[0][0]).toMatchObject({ request_id: requestId, parent_run_id: sourceId });
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('retains a real retry request across component reload before submission returns', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'older', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId ? source : { id, state: 'failed' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockImplementation(() => new Promise(() => {}));
  const first = render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить расчёт сети' }));
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1));
  const saved = JSON.parse(sessionStorage.getItem(`simulation:pending-feedback:${sceneId}`));
  expect(saved.retry).toBe(true);
  first.unmount();
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(2));
  expect(simulationApi.createFeedback.mock.calls.map(call => call[0].request_id)).toEqual([saved.requestId, saved.requestId]);
});

test('reports a second failed feedback attempt to the parent', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`, JSON.stringify({ version: 1, sourceId,
    requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e' }));
  const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  const onFailure = jest.fn();
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'older', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId ? source : { id, state: 'failed' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'again', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onFailure={onFailure} />);
  await waitFor(() => expect(onFailure).toHaveBeenCalledTimes(1));
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить расчёт сети' }));
  await waitFor(() => expect(onFailure).toHaveBeenCalledTimes(2));
});

test('reuses the same feedback request identity after an interrupted submission', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const requestId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
  sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`,
    JSON.stringify({ version: 1, sourceId, requestId }));
  const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.get.mockResolvedValue(source);
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockImplementation(() => new Promise(() => {}));
  const first = render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1));
  first.unmount();
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(2));
  expect(simulationApi.createFeedback.mock.calls.map(call => call[0].request_id)).toEqual([requestId, requestId]);
});

test('clears the saved receipt after an existing feedback calculation completes', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const key = `simulation:pending-feedback:${sceneId}`;
  sessionStorage.setItem(key, JSON.stringify({ version: 1, sourceId,
    requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e' }));
  const source = { id: sourceId, parent_run_id: sceneId, state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'coupled', state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId ? source : coupledRun(sourceId));
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
  expect(simulationApi.createFeedback).not.toHaveBeenCalled();
});

test.each([
  ['executor_feedback_iteration_limit', /не сошёлся за заданное число итераций/],
  ['executor_feedback_cycle', /повторяющееся расписание обратной связи/],
  ['executor_synapse_endpoint', /Синапс находится на конце секции/],
])('explains an unconverged coupled run without showing it as a result: %s', async (error, message) => {
  const show = jest.fn();
  const source = { id: 'saved', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'coupled', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? { id, state: 'failed', error,
    result: { feedback_failure: { history: [{ iteration: 1 }] } } } : source);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.getByText('Завершено итераций: 1.')).toBeInTheDocument();
  expect(show).not.toHaveBeenCalled();
});

test('restores an earlier verified result only after explicit selection following failure', async () => {
  const show = jest.fn();
  const source = { id: 'saved', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [
    { id: 'failed', state: 'failed' }, { id: 'coupled', state: 'completed' }] });
  const completed = coupledRun('saved');
  simulationApi.get.mockImplementation(async id => id === 'failed'
    ? { id, state: 'failed', error: 'executor_feedback_iteration_limit' }
    : id === 'coupled' ? completed : source);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  const open = await screen.findByRole('button', { name: 'Открыть предыдущий результат' });
  expect(show).not.toHaveBeenCalled();
  fireEvent.click(open);
  await waitFor(() => expect(show).toHaveBeenCalledWith(completed, { source, restore: true }));
});

test('checks all contacts before searching or submitting a calculation', async () => {
  const onFailure = jest.fn();
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ contact_indices: [0, 2] }] });
  simulationApi.contactPositions.mockImplementation(async (_id, request) => ({ potential_intersections: [{ contact_indices: request.positions_um.map((_, index) => index) }] }));
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onFailure={onFailure} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('не найдены допустимые положения контактов');
  expect(simulationApi.spatialCandidates).not.toHaveBeenCalled();
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
  expect(onFailure).toHaveBeenCalled();
});

test('preserves a newer contact draft if a previous submission finishes late', async () => {
  let finishCreate;
  const adjust = jest.fn();
  simulationApi.createFragmentPopulation.mockReturnValue(new Promise(resolve => { finishCreate = resolve; }));
  const { rerender } = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onAdjustContact={adjust} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1));
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [5, 6, 7] };
  const incoming = { kind: 'fragments', fieldRunId: 'other', simulation,
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } };
  rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onAdjustContact={adjust} incomingContacts={incoming} />);
  await act(async () => {});
  await act(async () => { finishCreate({ id: 'old-submission', state: 'queued' }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('изменённое положение сохранено как черновик');
  expect(adjust).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Контакты и клетки'));
  expect(screen.getByLabelText('STIM+ X')).toHaveValue('5');
});

test('reports a busy geometry service without creating a calculation', async () => {
  simulationApi.contactScreen.mockRejectedValue({ status: 429 });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('занята другим запросом');
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('excludes listed cells only on explicit confirmation and preserves the remaining population', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', fieldRunId: 'old', configuration: { graph_manifest_sha256: graph, source_ids: [1, 2, 3], simulation }, simulation };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'bad', state: 'failed', error: 'executor_synapse_geometries:1:2:100,2:1:100;omitted:0' }] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  expect(screen.getByLabelText('ID клеток через запятую')).toHaveValue('1, 2, 3');
  fireEvent.click(screen.getByRole('button', { name: 'Исключить перечисленные клетки' }));
  expect(screen.getByLabelText('ID клеток через запятую')).toHaveValue('3');
  expect(screen.getByText(/Исключены из следующего расчёта: 1, 2/)).toBeInTheDocument();
});

test('records the reduced population size and explicit exclusions in the new run title', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', fieldRunId: 'old', configuration: { graph_manifest_sha256: graph, source_ids: [1, 2, 3], simulation }, simulation };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'bad', state: 'failed', error: 'executor_synapse_geometries:1:2:100,2:1:100;omitted:0' }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Исключить перечисленные клетки' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.createFragmentPopulation).toHaveBeenCalledWith(expect.objectContaining({ title: 'STIM: выбранные клетки (1), исключено 2', configuration: expect.objectContaining({ source_ids: [3] }) }));
});

test('restores the failed run configuration and its contacts for explicit correction', async () => {
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [12, 13, 14] };
  const configuration = { graph_manifest_sha256: graph, source_ids: [1, 2, 3], simulation };
  const adjust = jest.fn();
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'bad', state: 'failed', configuration,
    error: 'executor_synapse_geometries:1:2:100,2:1:100;omitted:0' }] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onAdjustContact={adjust} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить параметры неудачного расчёта' }));
  expect(screen.getByLabelText('ID клеток через запятую')).toHaveValue('1, 2, 3');
  expect(screen.getByLabelText('STIM+ X')).toHaveValue('12');
  expect(adjust).toHaveBeenCalledWith({ kind: 'fragments', configuration, simulation }, null);
  fireEvent.click(screen.getByRole('button', { name: 'Исключить перечисленные клетки' }));
  expect(screen.getByLabelText('ID клеток через запятую')).toHaveValue('3');
});

test('an explicitly selected checked contact is passed to the scene and invalidates the source selection', async () => {
  const adjust = jest.fn();
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ contact_indices: [0] }] });
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [{ contact_indices: [0, 2, 3, 4, 5] }] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onAdjustContact={adjust} />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.click(screen.getByRole('button', { name: 'Проверить контакты' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить соседние точки' }));
  await screen.findByText('Без пересечений в проверенном снимке:');
  const positions = simulationApi.contactPositions.mock.calls[0][1].positions_um;
  const point = positions[1];
  fireEvent.click(screen.getByRole('button', { name: point.map(value => Number(value.toFixed(2))).join(' / ') }));
  expect(adjust).toHaveBeenCalledWith(expect.objectContaining({ simulation: expect.objectContaining({ source_um: point }) }), 'source_um');
  expect(screen.getByText(/При запуске будут найдены/)).toBeInTheDocument();
});

test('manual contact edits update the scene only after a valid blur and require reselection', async () => {
  const adjust = jest.fn();
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onAdjustContact={adjust} />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  const input = screen.getByLabelText('STIM+ X');
  fireEvent.focus(input); fireEvent.blur(input);
  expect(adjust).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '' } });
  fireEvent.blur(input);
  expect(adjust).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '430' } });
  fireEvent.blur(input);
  expect(adjust).toHaveBeenCalledWith(expect.objectContaining({ simulation: expect.objectContaining({ source_um: expect.arrayContaining([430]) }) }), 'source_um');
  expect(screen.getByText(/При запуске будут найдены/)).toBeInTheDocument();
});

test('discards contact screening if the draft changes during the check', async () => {
  let resolveScreen;
  simulationApi.contactScreen.mockReturnValue(new Promise(resolve => { resolveScreen = resolve; }));
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.contactScreen).toHaveBeenCalled());
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.change(screen.getByLabelText('STIM+ X'), { target: { value: '431' } });
  await act(async () => { resolveScreen({ potential_intersections: [] }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('изменились во время проверки');
  expect(simulationApi.spatialCandidates).not.toHaveBeenCalled();
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('main experiment form reports readiness and opens its completed calculation', async () => {
  const status = jest.fn(), show = jest.fn(), adjust = jest.fn(), form = React.createRef();
  const complete = { id: 'new', state: 'completed', configuration: { graph_manifest_sha256: graph,
    source_ids: [1, 2], simulation: fieldDemoPreset(graph).simulation }, result: { preview: {
    source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
  } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  const coupled = coupledRun('new');
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph, sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'coupled', state: 'queued' });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : complete);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} formRef={form}
    onPrimaryStatus={status} onShowOnBody={show} onAdjustContact={adjust} />);
  await waitFor(() => expect(status).toHaveBeenLastCalledWith({ ready: true, running: false }));
  await act(async () => { fireEvent.submit(form.current); });
  await waitFor(() => expect(show).toHaveBeenCalledWith(coupled, { source: complete, restore: false }));
  expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1);
  expect(adjust).toHaveBeenCalledWith(expect.objectContaining({ kind: 'fragments',
    configuration: expect.objectContaining({ graph_manifest_sha256: graph }) }), null);
});

test('restores a completed calculation associated with the current scene', async () => {
  const show = jest.fn();
  const operatorSimulation = { ...fieldDemoPreset(graph).simulation,
    source_um: [123, 234, 345], return_um: [321, 432, 543],
    electrode_um: [220, 330, 440], reference_um: [111, 222, 333] };
  const complete = { id: 'saved', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: operatorSimulation }, result: { preview: {
    source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
  } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  const coupled = coupledRun('saved');
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'coupled', state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : complete);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  await waitFor(() => expect(show).toHaveBeenCalledWith(coupled, { source: complete, restore: true }));
  expect(screen.queryByRole('button', { name: 'Показать ответ ЦНС' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Файлы результата' })).not.toBeInTheDocument();
  expect(screen.queryByText('Сигнал: 2')).not.toBeInTheDocument();
  expect(simulationApi.createFeedback).not.toHaveBeenCalled();
  expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalledWith(expect.anything(), 'scene');
  expect(show.mock.calls[0][1].source.configuration.simulation).toEqual(operatorSimulation);
});

test('opens the verified whole-network result with the physical recording', async () => {
  const show = jest.fn(), form = React.createRef();
  const complete = { id: 'new', state: 'completed', configuration: { graph_manifest_sha256: graph,
    source_ids: [1, 2], simulation: fieldDemoPreset(graph).simulation }, result: { preview: {
    source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
  } } };
  const proxy = { id: 'proxy', parent_run_id: 'new', state: 'completed' };
  useWholeNetworkProxy.mockReturnValue({ status: 'completed', run: proxy });
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph, sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'coupled', state: 'queued' });
  const coupled = coupledRun('new');
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : complete);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} formRef={form} onShowOnBody={show} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  await act(async () => { fireEvent.submit(form.current); });
  await waitFor(() => expect(show).toHaveBeenCalledWith(coupled, { source: complete, restore: false, proxy }));
});

test('does not overwrite an edited draft when an older coupled calculation loads', async () => {
  const show = jest.fn();
  const source = { id: 'saved', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { preview: { source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'saved', state: 'completed' }] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'coupled', state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupledRun('saved') : source);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} canRestore={() => false} onShowOnBody={show} />);
  await screen.findByRole('button', { name: 'Показать ответ ЦНС' });
  expect(show).not.toHaveBeenCalled();
});

test('does not display the source as a coupled result when feedback fails', async () => {
  const show = jest.fn(), failure = jest.fn(), form = React.createRef();
  const source = { id: 'new', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph }, result: { preview: {
      source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
    } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'feedback', state: 'queued' });
  simulationApi.get.mockImplementation(async id => id === 'feedback'
    ? { id: 'feedback', state: 'failed' } : source);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} formRef={form}
    onShowOnBody={show} onFailure={failure} />);
  await act(async () => {});
  await act(async () => { fireEvent.submit(form.current); });
  expect(await screen.findByRole('alert')).toHaveTextContent('ответ сети на сцене не показан');
  expect(show).not.toHaveBeenCalled();
  expect(failure).toHaveBeenCalledTimes(1);
});

test('zero current is submitted explicitly for a control run', async () => {
  const status = jest.fn();
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onPrimaryStatus={status} />);
  await waitFor(() => expect(status).toHaveBeenLastCalledWith({ ready: true, running: false }));
  fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '0' } });
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0].configuration.simulation.current_na).toBe(0);
});

test('reports the physical calculation stage to the main screen', async () => {
  const status = jest.fn();
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'running', state: 'running' }] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onPrimaryStatus={status} />);
  await waitFor(() => expect(status).toHaveBeenLastCalledWith(expect.objectContaining({ ready: false, running: true, stage: 'Расчёт нейронов', phase: 1 })));
});

test('submits the chosen observation duration and rejects a window shorter than the pulse', async () => {
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  const input = screen.getByLabelText('Длительность, мс');
  fireEvent.change(input, { target: { value: '3' } });
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeDisabled();
  fireEvent.change(input, { target: { value: '50' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0].configuration.simulation.duration_ms).toBe(50);
});

test('submits explicit cells and the edited physical contact without claiming whole-network coverage', async () => {
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  await act(async () => {});
  expect(screen.getByText(/Запись рассчитана для выбранных клеток/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.change(screen.getByLabelText('STIM+ Y'), { target: { value: '388.5' } });
  fireEvent.change(screen.getByLabelText('ID клеток через запятую'), { target: { value: '174827, 176609' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1));
  const payload = simulationApi.createFragmentPopulation.mock.calls[0][0];
  expect(payload.configuration.source_ids).toEqual([174827, 176609]);
  expect(payload.configuration.simulation.source_um).toEqual([429.056, 388.5, 228.352]);
  expect(payload.configuration.simulation.allow_disconnected).toBe(true);
});

test('does not submit unsupported graph or repeated cells', async () => {
  render(<FragmentPopulationRecording sceneManifest="unknown" />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('ID клеток через запятую'), { target: { value: '1, 1' } });
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeDisabled();
});

test('displays actual saved signal and limitations', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'one', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'one', result: { preview: {
    source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0.1], limitations: ['Нет обратной связи.'],
  } } });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByText(/событий на выходах: 0/)).toBeInTheDocument();
  expect(screen.getByText('Сигнал: 2')).toBeInTheDocument();
  expect(screen.getByText('Нет обратной связи.')).toBeInTheDocument();
});

test('loads and downloads artifacts from the selected run', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'one', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'one', state: 'completed', result: { preview: {
    source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
  } } });
  simulationApi.artifacts.mockResolvedValue({ items: [{ id: 'file', name: 'signals.npz' }] });
  simulationApi.download.mockResolvedValue();
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Файлы результата' }));
  fireEvent.click(await screen.findByRole('button', { name: 'signals.npz' }));
  expect(simulationApi.download).toHaveBeenCalledWith('one', { id: 'file', name: 'signals.npz' });
});

test('stops an active calculation', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'busy', state: 'running' }] });
  simulationApi.cancel.mockResolvedValue({});
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  const button = await screen.findByRole('button', { name: 'Остановить' });
  await act(async () => { fireEvent.click(button); });
  expect(simulationApi.cancel).toHaveBeenCalledWith('busy');
});

test('offers scene playback only for a matching graph and saved event journal', async () => {
  const show = jest.fn();
  const run = { id: 'one', state: 'completed', configuration: { graph_manifest_sha256: graph,
    source_ids: [1], simulation: fieldDemoPreset(graph).simulation },
    result: { manifest: { files: [{ name: 'fragment-events.bin' }] }, preview: {
      source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
    } } };
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'one', state: 'completed' }] });
  const coupled = coupledRun('one');
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'coupled', state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : run);
  render(<FragmentPopulationRecording sceneManifest={graph} onShowOnBody={show} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Показать ответ ЦНС' }));
  expect(show).toHaveBeenCalledWith(coupled, { source: run });
});

test('uses scene contact edits while preserving the original calculation settings', async () => {
  const simulation = { ...fieldDemoPreset(graph).simulation, allow_disconnected: true, current_na: -120 };
  const config = { graph_manifest_sha256: graph, source_ids: [16827], seed: 23,
    simulation, threshold_mv: -25, max_distance_um: 1.5 };
  const incoming = { kind: 'fragments', configuration: config,
    simulation: { ...simulation, source_um: [5, 6, 7] } };
  const consume = jest.fn();
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'old', state: 'completed' }] });
  simulationApi.get.mockResolvedValue({ id: 'old', state: 'completed', configuration: config, result: { preview: {
    source_cells: 1, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
  } } });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneManifest={graph} incomingContacts={incoming} onConsumeContacts={consume} />);
  await act(async () => {});
  expect(consume).toHaveBeenCalledTimes(1);
  expect(await screen.findByText(/Показана запись сохранённого расчёта/)).toBeInTheDocument();
  expect(screen.getByText(/При запуске будут найдены/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.change(screen.getByLabelText('ID клеток через запятую'), { target: { value: '16827, 1' } });
  fireEvent.change(screen.getByLabelText('ID клеток через запятую'), { target: { value: '16827' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  const sent = simulationApi.createFragmentPopulation.mock.calls[0][0].configuration;
  expect(sent.source_ids).toEqual([16827]);
  expect(sent.simulation.source_um).toEqual([5, 6, 7]);
  expect(sent.simulation.current_na).toBe(-120);
  expect(sent.seed).toBe(23);
  expect(sent.threshold_mv).toBe(-25);
  expect(sent.max_distance_um).toBe(1.5);
});

test('rejects scene coordinates from another graph', async () => {
  const consume = jest.fn();
  const incoming = { kind: 'fragments', configuration: { graph_manifest_sha256: 'b'.repeat(64), source_ids: [1] },
    simulation: fieldDemoPreset(graph).simulation };
  render(<FragmentPopulationRecording sceneManifest={graph} incomingContacts={incoming} onConsumeContacts={consume} />);
  await act(async () => {});
  expect(await screen.findByRole('alert')).toHaveTextContent('проверьте совместимость графа');
  expect(consume).toHaveBeenCalledTimes(1);
});

test('uses the complete eligible geometric selection and does not claim excitation', async () => {
  const candidate = { body_id: 16827, child_node_id: 4, distance_um: 7.85, contact: 0,
    isolated_root: false, edge_fraction: 0.5, conservative_clearance_um: [7, 100],
    recording_clearance_um: [20, 100],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByText(/не подтверждение возбуждения/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Заменить источники найденными (1)' }));
  expect(screen.getByLabelText('ID клеток через запятую')).toHaveValue('16827');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0].configuration.source_ids).toEqual([16827]);
});

test('moving a contact reselects geometry before starting the calculation', async () => {
  const candidate = { body_id: 16827, child_node_id: 4, distance_um: 7.85, contact: 0,
    isolated_root: false, edge_fraction: 0.5, conservative_clearance_um: [7, 100],
    recording_clearance_um: [20, 100],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Заменить источники найденными (1)' }));
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled();
  fireEvent.change(screen.getByLabelText('STIM+ X'), { target: { value: '430' } });
  expect(screen.getByText(/При запуске будут найдены/)).toBeInTheDocument();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates).toHaveBeenCalledTimes(2);
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0].configuration.source_ids).toEqual([16827]);
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0].configuration.simulation.source_um[0]).toBe(430);
});

test('automatic selection does not start if no compatible morphology is found', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', configuration: { graph_manifest_sha256: graph, source_ids: [16827], simulation },
    simulation: { ...simulation, source_um: [430, ...simulation.source_um.slice(1)] } };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('не найдены подходящие реконструкции');
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('fresh scene preset IDs do not bypass spatial selection', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', configuration: { graph_manifest_sha256: graph, source_ids: [174827, 176609], simulation }, simulation };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates.mock.calls.map(call => call[1].radius_um)).toEqual([10, 20, 40, 80, 160, 200]);
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('automatic selection uses the explicitly chosen search radius', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation }, simulation };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.change(screen.getByLabelText('Радиус автоматического поиска, мкм'), { target: { value: '6' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates.mock.calls[0][1].radius_um).toBe(6);
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('automatic search narrows the radius instead of truncating sources', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation }, simulation };
  const candidate = id => ({ body_id: id, child_node_id: 4, isolated_root: false, edge_fraction: 0.5,
    conservative_clearance_um: [7, 100], recording_clearance_um: [20, 100],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } });
  simulationApi.spatialCandidates.mockResolvedValueOnce({ candidates: Array.from({ length: 257 }, (_, i) => candidate(i + 1)) })
    .mockResolvedValueOnce({ candidates: [candidate(5), candidate(6)] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates.mock.calls.map(call => call[1].radius_um)).toEqual([10, 5]);
  const payload = simulationApi.createFragmentPopulation.mock.calls[0][0];
  expect(payload.configuration.source_ids).toEqual([5, 6]);
  expect(payload.title).toBe('STIM: радиус 5 мкм, клеток 2');
});

test('reuses complete spatial results when narrowing the search radius', async () => {
  const candidate = id => ({ body_id: id, child_node_id: 4, distance_um: id <= 2 ? 4 : 9,
    isolated_root: false, edge_fraction: .5, conservative_clearance_um: [7, 100],
    recording_clearance_um: [20, 100], geometry: { components: 1, isolated_roots: 0,
      zero_length_edges: 0, nonpositive_radius_edges: 0 } });
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: Array.from({ length: 257 }, (_, i) => candidate(i + 1)) });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates).toHaveBeenCalledTimes(1);
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0]).toEqual(expect.objectContaining({
    title: 'STIM: радиус 5 мкм, клеток 2', configuration: expect.objectContaining({ source_ids: [1, 2] }),
  }));
});

test('discard automatic selection when contacts change during the search', async () => {
  const simulation = fieldDemoPreset(graph).simulation;
  const incoming = { kind: 'fragments', configuration: { graph_manifest_sha256: graph, source_ids: [16827], simulation },
    simulation: { ...simulation, source_um: [430, ...simulation.source_um.slice(1)] } };
  let resolveSearch;
  simulationApi.spatialCandidates.mockReturnValue(new Promise(resolve => { resolveSearch = resolve; }));
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.spatialCandidates).toHaveBeenCalled());
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.change(screen.getByLabelText('STIM+ X'), { target: { value: '431' } });
  await act(async () => { resolveSearch({ candidates: [] }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('изменились во время поиска');
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('does not silently truncate more than 256 geometric candidates', async () => {
  const rows = Array.from({ length: 257 }, (_, index) => ({ body_id: index + 1, child_node_id: 4,
    distance_um: 7, contact: 0, isolated_root: false, edge_fraction: 0.5,
    conservative_clearance_um: [7, 100], recording_clearance_um: [20, 100],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } }));
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: rows });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  fireEvent.click(screen.getByText('Контакты и клетки'));
  fireEvent.click(screen.getByText('Поиск отростков рядом со STIM'));
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  expect(await screen.findByRole('button', { name: 'Заменить источники найденными (257)' })).toBeDisabled();
  expect(screen.getByText(/Состав не помещается в запрос/)).toBeInTheDocument();
});

test('explains unresolved synapse geometry', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error: 'executor_synapse_geometry' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Не все синапсы удалось сопоставить');
});

test('opens an explicitly selected earlier completed STIM calculation', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [
    { id: 'newer', state: 'completed', title: 'Новый' },
    { id: 'older', state: 'completed', title: 'Ранее' },
  ] });
  simulationApi.get.mockImplementation(async id => ({ id, state: 'completed', configuration: {
    source_ids: [174827, 176609], simulation: fieldDemoPreset(graph).simulation,
  }, result: { preview: { time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } }));
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  const select = await screen.findByLabelText('Завершённый STIM-расчёт');
  await waitFor(() => expect(select).toHaveValue('newer'));
  fireEvent.change(select, { target: { value: 'older' } });
  await waitFor(() => expect(select).toHaveValue('older'));
  expect(simulationApi.get).toHaveBeenCalledWith('older', expect.anything());
});

test('explains an incompatible generator version', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed',
    error: 'executor_endpoint_missing' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Обновите сервис генератора');
});

test('identifies the source and count for unresolved synapse geometry', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error: 'executor_synapse_geometry:512731:2:1199' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Нейрон 512731: не удалось сопоставить 2 из 1199 синапсов');
});

test('shows multiple unresolved cells and explicitly reports additional failures', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed',
    error: 'executor_synapse_geometries:174827:2:1199,176609:22:2772;omitted:3' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByText('Нейрон 174827: 2 из 1199.')).toBeInTheDocument();
  expect(screen.getByText('Нейрон 176609: 22 из 2772.')).toBeInTheDocument();
  expect(screen.getByText('Ещё клеток с расхождениями: 3.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Исключить 174827' }));
  expect(screen.getByText('Исключены из следующего расчёта: 174827.')).toBeInTheDocument();
});

test('requires explicit exclusion and marks the reduced source coverage', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error: 'executor_synapse_geometry:174827:2:1199' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  const button = await screen.findByRole('button', { name: 'Исключить нейрон 174827' });
  expect(screen.getByText(/не будет включать исключённую клетку/)).toBeInTheDocument();
  fireEvent.click(button);
  expect(screen.getByText('Исключены из следующего расчёта: 174827.')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Контакты и клетки'));
  expect(screen.getByLabelText('ID клеток через запятую')).toHaveValue('176609');
  expect(screen.queryByRole('button', { name: 'Исключить нейрон 174827' })).not.toBeInTheDocument();
});
