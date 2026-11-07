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

test('exposes completed source files only when the source belongs to the current scene and graph', async () => {
  const source = { id: 'source', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1] } };
  const report = jest.fn();
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: source.id, state: 'completed' }] });
  simulationApi.get.mockResolvedValue(source);
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onSourceForFiles={report} />);
  await waitFor(() => expect(report).toHaveBeenLastCalledWith({ sceneRunId: 'scene', source }));
  view.rerender(<Recording sceneRunId="other" sceneManifest={graph} onSourceForFiles={report} />);
  await waitFor(() => expect(report).toHaveBeenLastCalledWith(null));
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
  let sourceConfiguration, requestSequence = 0;
  const onFailure = jest.fn();
  global.crypto = { randomUUID: () => `e3ab7f7a-2d15-4fd1-93a3-${String(++requestSequence).padStart(12, '0')}` };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockImplementation(async payload => {
    sourceConfiguration = payload.configuration;
    return { id: sourceId, state: 'queued' };
  });
  simulationApi.feedbackRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'older', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId
    ? { id, parent_run_id: sceneId, state: 'completed', configuration: sourceConfiguration }
    : { id, state: 'failed' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValueOnce({ id: 'older', state: 'queued' })
    .mockImplementation(() => new Promise(() => {}));
  const first = render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onFailure={onFailure} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(onFailure).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(2));
  const saved = JSON.parse(sessionStorage.getItem(`simulation:pending-feedback:${sceneId}`));
  expect(saved.retry).toBe(true);
  first.unmount();
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(3));
  expect(simulationApi.createFeedback.mock.calls.slice(1).map(call => call[0].request_id))
    .toEqual([saved.requestId, saved.requestId]);
  expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1);
});

test.each(['unchanged', 'current', 'pulse'])('after reload checks the whole draft before network retry: %s', async edited => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  let sourceConfiguration, requestSequence = 0;
  const onFailure = jest.fn();
  global.crypto = { randomUUID: () => `e3ab7f7a-2d15-4fd1-93a3-${String(++requestSequence).padStart(12, '0')}` };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockImplementation(async payload => {
    sourceConfiguration = payload.configuration;
    return { id: sourceId, state: 'queued' };
  });
  simulationApi.feedbackRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'failed-feedback', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId
    ? { id, parent_run_id: sceneId, state: 'completed', configuration: sourceConfiguration }
    : { id, state: 'failed' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValueOnce({ id: 'failed-feedback', state: 'queued' })
    .mockResolvedValueOnce({ id: 'new-feedback', state: 'queued' });
  const first = render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onFailure={onFailure} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '-265' } });
  fireEvent.change(screen.getByLabelText('Радиус поиска, мкм'), { target: { value: '15' } });
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(onFailure).toHaveBeenCalledTimes(1));
  first.unmount();
  const restoredConfiguration = JSON.parse(JSON.stringify(sourceConfiguration));
  if (edited === 'pulse') restoredConfiguration.simulation.pulse_start_ms += .1;
  const incomingContacts = { kind: 'fragments', configuration: restoredConfiguration,
    simulation: restoredConfiguration.simulation, fieldRunId: sourceId };
  const adjust = jest.fn();
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph}
    incomingContacts={edited === 'pulse' ? incomingContacts : undefined} onAdjustContact={adjust} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  await waitFor(() => expect(simulationApi.feedbackRuns).toHaveBeenCalledTimes(2));
  if (edited !== 'pulse') {
    await waitFor(() => expect(screen.getByLabelText('Ток STIM, нА')).toHaveValue(-265));
    expect(screen.getByLabelText('Радиус поиска, мкм')).toHaveValue(15);
    expect(adjust).toHaveBeenCalledWith(expect.objectContaining({ simulation: sourceConfiguration.simulation }), null);
  } else fireEvent.change(screen.getByLabelText('Радиус поиска, мкм'), { target: { value: '15' } });
  if (edited === 'current') fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '-250' } });
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  if (edited !== 'unchanged') {
    await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(2));
    if (edited === 'current') expect(simulationApi.createFragmentPopulation.mock.calls[1][0].configuration.simulation.current_na).toBe(-250);
  } else {
    await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(2));
    expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1);
  }
});

test('does not replace a new operator edit while a failed source is being restored', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const simulation = { ...fieldDemoPreset(graph).simulation, current_na: -265 };
  const configuration = { graph_manifest_sha256: graph, source_ids: [1, 2], seed: 1,
    threshold_mv: -20, max_distance_um: 2, simulation };
  const positions = Object.fromEntries(['source_um', 'return_um', 'electrode_um', 'reference_um']
    .map(key => [key, simulation[key]]));
  sessionStorage.setItem(`simulation:feedback-retry-draft:${sceneId}`, JSON.stringify({ version: 1, sourceId,
    signature: JSON.stringify([sceneId, graph, positions, -265, simulation.duration_ms, '1, 2', '15']) }));
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId
    ? { id, parent_run_id: sceneId, state: 'completed', configuration }
    : { id, state: 'failed' });
  let finishList;
  simulationApi.feedbackRuns.mockReturnValue(new Promise(resolve => { finishList = resolve; }));
  const adjust = jest.fn();
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onAdjustContact={adjust} />);
  await waitFor(() => expect(simulationApi.feedbackRuns).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '-200' } });
  await act(async () => finishList({ items: [{ id: 'failed-feedback', state: 'failed' }] }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  expect(screen.getByLabelText('Ток STIM, нА')).toHaveValue(-200);
  expect(adjust).not.toHaveBeenCalled();
});

test('allows restoring a failed draft after the scene delivers its untouched preset', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const simulation = { ...fieldDemoPreset(graph).simulation, current_na: -265 };
  const configuration = { graph_manifest_sha256: graph, source_ids: [1, 2], seed: 1,
    threshold_mv: -20, max_distance_um: 2, simulation };
  const positions = Object.fromEntries(['source_um', 'return_um', 'electrode_um', 'reference_um']
    .map(key => [key, simulation[key]]));
  sessionStorage.setItem(`simulation:feedback-retry-draft:${sceneId}`, JSON.stringify({ version: 1, sourceId,
    signature: JSON.stringify([sceneId, graph, positions, -265, simulation.duration_ms, '1, 2', '15']) }));
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId
    ? { id, parent_run_id: sceneId, state: 'completed', configuration }
    : { id, state: 'failed' });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [{ id: 'failed-feedback', state: 'failed' }] });
  const preset = fieldDemoPreset(graph), adjust = jest.fn(), consume = jest.fn();
  const incoming = { kind: 'fragments', configuration: { ...configuration, simulation: preset.simulation },
    simulation: preset.simulation, changed: false };
  const view = render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph}
    canRestore={() => true} onAdjustContact={adjust} onConsumeContacts={consume} incomingContacts={incoming} />);
  await waitFor(() => expect(consume).toHaveBeenCalled());
  view.rerender(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph}
    canRestore={() => true} onAdjustContact={adjust} onConsumeContacts={consume} />);
  await waitFor(() => expect(screen.getByLabelText('Ток STIM, нА')).toHaveValue(-265));
  expect(screen.getByLabelText('Радиус поиска, мкм')).toHaveValue(15);
  expect(adjust).toHaveBeenCalledWith(expect.objectContaining({ simulation }), null);
});

test('reports a second failed feedback attempt to the parent', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  let sourceConfiguration, requestSequence = 0;
  const onFailure = jest.fn(), show = jest.fn();
  global.crypto = { randomUUID: () => `e3ab7f7a-2d15-4fd1-93a3-${String(++requestSequence).padStart(12, '0')}` };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: sourceId, state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockImplementation(async payload => {
    sourceConfiguration = payload.configuration;
    return { id: sourceId, state: 'queued' };
  });
  simulationApi.feedbackRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'older', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === sourceId
    ? { id, parent_run_id: sceneId, state: 'completed', configuration: sourceConfiguration }
    : { id, state: 'failed' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValueOnce({ id: 'older', state: 'queued' })
    .mockResolvedValueOnce({ id: 'again', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph}
    onFailure={onFailure} onShowOnBody={show} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(onFailure).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(onFailure).toHaveBeenCalledTimes(2));
  expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1);
  expect(show).not.toHaveBeenCalled();
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

test('does not display a previous result after the latest calculation failed', async () => {
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
  expect(await screen.findByText(/не сошёлся за заданное число итераций/)).toBeInTheDocument();
  expect(show).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Открыть предыдущий результат' })).not.toBeInTheDocument();
});

test('checks all contacts before searching or submitting a calculation', async () => {
  const onFailure = jest.fn();
  simulationApi.contactScreen.mockResolvedValue({ potential_intersections: [{ contact_indices: [0, 2] }] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onFailure={onFailure} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Контакты STIM+, E1 слишком близко к отросткам');
  expect(simulationApi.contactScreen).toHaveBeenCalledWith('scene', expect.objectContaining({
    source_um: expect.any(Array), return_um: expect.any(Array),
    electrode_um: expect.any(Array), reference_um: expect.any(Array),
  }), expect.any(AbortSignal));
  expect(simulationApi.contactPositions).not.toHaveBeenCalled();
  expect(simulationApi.spatialCandidates).not.toHaveBeenCalled();
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
  expect(onFailure).toHaveBeenCalled();
});

test('preserves a newer contact draft if a previous submission finishes late', async () => {
  let finishCreate;
  const adjust = jest.fn();
  const report = jest.fn();
  simulationApi.createFragmentPopulation.mockReturnValue(new Promise(resolve => { finishCreate = resolve; }));
  const { rerender } = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onAdjustContact={adjust} onPrimaryStatus={report} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1));
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [5, 6, 7] };
  const incoming = { kind: 'fragments', fieldRunId: 'other', simulation,
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } };
  rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onAdjustContact={adjust} onPrimaryStatus={report} incomingContacts={incoming} />);
  await act(async () => {});
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'old-submission', state: 'queued' }] });
  await act(async () => { finishCreate({ id: 'old-submission', state: 'queued' }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('изменённое положение сохранено как черновик');
  expect(adjust).not.toHaveBeenCalled();
  await waitFor(() => expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ running: true, canCancel: true })));
  await act(async () => { await report.mock.lastCall[0].cancel(); });
  expect(simulationApi.cancel).toHaveBeenCalledWith('old-submission');
});

test('does not attach a late submission to a different scene', async () => {
  const oldScene = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const newScene = '71852bf2-a4cf-430e-ab0a-ff5866d1c300';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  let finishCreate;
  const show = jest.fn(), status = jest.fn();
  simulationApi.createFragmentPopulation.mockReturnValue(new Promise(resolve => { finishCreate = resolve; }));
  const view = render(<FragmentPopulationRecording sceneRunId={oldScene} sceneManifest={graph}
    onShowOnBody={show} onPrimaryStatus={status} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1));
  view.rerender(<FragmentPopulationRecording sceneRunId={newScene} sceneManifest={graph}
    onShowOnBody={show} onPrimaryStatus={status} />);
  await act(async () => { finishCreate({ id: sourceId, state: 'queued' }); });
  expect(status).toHaveBeenLastCalledWith({ ready: true, running: false });
  expect(show).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(`simulation:pending-feedback:${oldScene}`)).toContain(sourceId);
  expect(sessionStorage.getItem(`simulation:pending-feedback:${newScene}`)).toBeNull();
});

test('does not replace an edited contact draft when its earlier calculation completes', async () => {
  let finishCreate;
  const show = jest.fn(), adjust = jest.fn();
  simulationApi.createFragmentPopulation.mockReturnValue(new Promise(resolve => { finishCreate = resolve; }));
  const oldSimulation = fieldDemoPreset(graph).simulation;
  const source = { id: 'older', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1, 2], simulation: oldSimulation },
    result: { preview: { source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  const coupled = coupledRun('older');
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'coupled', state: 'queued' });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : source);
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onShowOnBody={show} onAdjustContact={adjust} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1));
  const simulation = { ...oldSimulation, source_um: [5, 6, 7] };
  view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onShowOnBody={show} onAdjustContact={adjust} incomingContacts={{ kind: 'fragments', simulation,
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } }} />);
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'older', state: 'completed' }] });
  await act(async () => { finishCreate({ id: 'older', state: 'queued' }); });
  await waitFor(() => expect(simulationApi.get).toHaveBeenCalledWith('coupled', expect.anything()));
  expect(show).not.toHaveBeenCalled();
  expect(adjust).not.toHaveBeenCalled();
});

test('keeps a contact edited after launch when the calculation later completes', async () => {
  const originalSocket = global.WebSocket;
  let socket;
  global.WebSocket = class { constructor() { socket = this; } close() {} };
  simulationApi.eventsUrl = jest.fn(() => 'ws://localhost/test');
  const show = jest.fn();
  const oldSimulation = fieldDemoPreset(graph).simulation;
  const source = { id: 'new', parent_run_id: 'scene', state: 'completed',
    configuration: { graph_manifest_sha256: graph, source_ids: [1, 2], simulation: oldSimulation },
    result: { preview: { source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [] } } };
  const coupled = coupledRun('new');
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'running' }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'coupled', state: 'queued' });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : source);
  try {
    const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
    await waitFor(() => expect(socket?.onmessage).toBeDefined());
    const simulation = { ...oldSimulation, source_um: [5, 6, 7] };
    view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show}
      incomingContacts={{ kind: 'fragments', simulation,
        configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } }} />);
    simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
    act(() => socket.onmessage({ data: JSON.stringify({ type: 'snapshot', run: { id: 'new', state: 'completed' } }) }));
    await waitFor(() => expect(simulationApi.get).toHaveBeenCalledWith('coupled', expect.anything()));
    expect(show).not.toHaveBeenCalled();
  } finally { global.WebSocket = originalSocket; }
});

test('reports a busy geometry service without creating a calculation', async () => {
  simulationApi.contactScreen.mockRejectedValue({ status: 429 });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(await screen.findByRole('alert')).toHaveTextContent('занята другим запросом');
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('restores the failed source contacts for correction without reviving manual cell controls', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [12, 13, 14] };
  const configuration = { graph_manifest_sha256: graph, source_ids: [1, 2, 3], simulation };
  const adjust = jest.fn();
  const positions = Object.fromEntries(['source_um', 'return_um', 'electrode_um', 'reference_um']
    .map(key => [key, simulation[key]]));
  sessionStorage.setItem(`simulation:feedback-retry-draft:${sceneId}`, JSON.stringify({ version: 1, sourceId,
    signature: JSON.stringify([sceneId, graph, positions, simulation.current_na, simulation.duration_ms, '1, 2, 3', '15']) }));
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, parent_run_id: sceneId,
    state: 'failed', configuration,
    error: 'executor_synapse_geometries:1:2:100,2:1:100;omitted:0' }] });
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onAdjustContact={adjust} />);
  await waitFor(() => expect(adjust).toHaveBeenCalledWith({ kind: 'fragments', configuration, simulation }, null));
  expect(screen.getByLabelText('Радиус поиска, мкм')).toHaveValue(15);
  expect(screen.queryByLabelText('ID клеток через запятую')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('2 нейронов');
});

test.each(['edited', 'wrong-scene', 'mismatched-contact'])(
  'does not restore a failed source when its saved draft is unsafe: %s', async reason => {
    const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
    const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
    const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [12, 13, 14] };
    const configuration = { graph_manifest_sha256: graph, source_ids: [1, 2, 3], simulation };
    const positions = Object.fromEntries(['source_um', 'return_um', 'electrode_um', 'reference_um']
      .map(key => [key, simulation[key]]));
    if (reason === 'mismatched-contact') positions.source_um = [15, 16, 17];
    sessionStorage.setItem(`simulation:feedback-retry-draft:${sceneId}`, JSON.stringify({ version: 1, sourceId,
      signature: JSON.stringify([sceneId, graph, positions, simulation.current_na, simulation.duration_ms, '1, 2, 3', '15']) }));
    simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId,
      parent_run_id: reason === 'wrong-scene' ? 'other' : sceneId, state: 'failed', configuration,
      error: 'executor_synapse_geometries:1:2:100,2:1:100;omitted:0' }] });
    const adjust = jest.fn();
    render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onAdjustContact={adjust}
      canRestore={() => reason !== 'edited'} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('2 нейронов'));
    expect(adjust).not.toHaveBeenCalled();
  });

test('discards contact screening if the draft changes during the check', async () => {
  let resolveScreen;
  simulationApi.contactScreen.mockReturnValue(new Promise(resolve => { resolveScreen = resolve; }));
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.contactScreen).toHaveBeenCalled());
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [431, 387, 228] };
  view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    incomingContacts={{ kind: 'fragments', simulation,
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } }} />);
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

test('forwards real whole-network progress and cancellation to the main panel', async () => {
  const report = jest.fn();
  const complete = { id: 'new', state: 'completed', configuration: { graph_manifest_sha256: graph,
    source_ids: [1, 2], simulation: fieldDemoPreset(graph).simulation }, result: { preview: {
    source_cells: 2, edge_event_count: 0, time_ms: [0, 1], neural_uv: [0, 0], limitations: [],
  } } };
  const progress = { phase: 'network', done: 20, total: 100, runId: 'proxy' };
  useWholeNetworkProxy.mockReturnValue({ status: 'running', run: { id: 'proxy' }, progress });
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'coupled', state: 'queued' });
  const coupled = coupledRun('new');
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupled : complete);
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onPrimaryStatus={report} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(report).toHaveBeenLastCalledWith(expect.objectContaining({
    stage: 'Модель всей сети ЦНС', running: true, canCancel: true, progress,
  })));
  await act(async () => { await report.mock.lastCall[0].cancel(); });
  expect(simulationApi.cancel).toHaveBeenCalledWith('proxy');
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
  await waitFor(() => expect(simulationApi.get).toHaveBeenCalledWith('coupled', expect.anything()));
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

test.each([false, true])('main launch handles failed network stage with changed current: %s', async changed => {
  const failure = jest.fn(), show = jest.fn();
  let sourceConfiguration, sourceCount = 0, requestSequence = 0;
  global.crypto = { randomUUID: () => `e3ab7f7a-2d15-4fd1-93a3-${String(++requestSequence).padStart(12, '0')}` };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockImplementation(async payload => {
    sourceCount += 1; sourceConfiguration = payload.configuration;
    return { id: sourceCount === 1 ? 'new' : 'next', state: 'queued' };
  });
  simulationApi.feedbackRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'failed-feedback', state: 'failed' }] });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValueOnce({ id: 'failed-feedback', state: 'queued' })
    .mockResolvedValue({ id: 'coupled', state: 'queued' });
  simulationApi.get.mockImplementation(async id => {
    if (id === 'failed-feedback') return { id, state: 'failed' };
    if (id === 'coupled') return coupledRun('new');
    return { id, state: 'completed', parent_run_id: 'scene', configuration: sourceConfiguration,
      result: { preview: { source_cells: 2, time_ms: [0, 1], neural_uv: [0, 0] } } };
  });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    onFailure={failure} onShowOnBody={show} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(failure).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  if (changed) fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '-200' } });
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  if (changed) {
    await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(2));
    expect(simulationApi.createFragmentPopulation.mock.calls[1][0].configuration.simulation.current_na).toBe(-200);
  } else {
    await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(2));
    expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1);
    expect(simulationApi.createFeedback.mock.calls[1][0].parent_run_id).toBe('new');
    expect(simulationApi.createFeedback.mock.calls[1][0].request_id)
      .not.toBe(simulationApi.createFeedback.mock.calls[0][0].request_id);
  }
});

test.each([false, true])('main launch retries failed full-network proxy only for unchanged source: %s', async changed => {
  const failure = jest.fn(), retry = jest.fn();
  let sourceConfiguration;
  useWholeNetworkProxy.mockReturnValue({ status: 'failed', run: { id: 'proxy' }, retry });
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockImplementation(async payload => {
    sourceConfiguration = payload.configuration; return { id: 'new', state: 'queued' };
  });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValue({ id: 'coupled', state: 'queued' });
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? coupledRun('new')
    : { id, state: 'completed', parent_run_id: 'scene', configuration: sourceConfiguration });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onFailure={failure} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(failure).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  if (changed) fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '-200' } });
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  if (changed) {
    await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(2));
    expect(retry).not.toHaveBeenCalled();
  } else {
    expect(retry).toHaveBeenCalledTimes(1);
    expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1);
    expect(simulationApi.createFeedback).toHaveBeenCalledTimes(1);
  }
});

test('main launch reuses the same network retry request after a lost submission response', async () => {
  const failure = jest.fn();
  let sourceConfiguration, requestSequence = 0;
  global.crypto = { randomUUID: () => `e3ab7f7a-2d15-4fd1-93a3-${String(++requestSequence).padStart(12, '0')}` };
  simulationApi.fragmentPopulationRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'new', state: 'completed' }] });
  simulationApi.createFragmentPopulation.mockImplementation(async payload => {
    sourceConfiguration = payload.configuration;
    return { id: 'new', state: 'queued' };
  });
  simulationApi.feedbackRuns.mockResolvedValueOnce({ items: [] })
    .mockResolvedValue({ items: [{ id: 'failed-feedback', state: 'failed' }] });
  simulationApi.feedbackSource.mockResolvedValue({ graph_manifest_sha256: graph,
    sha256: 'a'.repeat(64), manifest_sha256: 'b'.repeat(64) });
  simulationApi.createFeedback.mockResolvedValueOnce({ id: 'failed-feedback', state: 'queued' })
    .mockRejectedValueOnce(new Error('connection interrupted'))
    .mockResolvedValueOnce({ id: 'coupled', state: 'queued' });
  simulationApi.get.mockImplementation(async id => {
    if (id === 'failed-feedback') return { id, state: 'failed' };
    if (id === 'coupled') return coupledRun('new');
    return { id, state: 'completed', parent_run_id: 'scene', configuration: sourceConfiguration,
      result: { preview: { source_cells: 2, time_ms: [0, 1], neural_uv: [0, 0] } } };
  });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onFailure={failure} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(failure).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(failure).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFeedback).toHaveBeenCalledTimes(3));
  expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1);
  expect(simulationApi.createFeedback.mock.calls[1][0].request_id)
    .toBe(simulationApi.createFeedback.mock.calls[2][0].request_id);
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

test('preserves the scene observation duration and rejects a window shorter than the pulse', async () => {
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  const makeDraft = duration => {
    const simulation = { ...fieldDemoPreset(graph).simulation, duration_ms: duration };
    return { kind: 'fragments', simulation,
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } };
  };
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    incomingContacts={makeDraft(3)} />);
  await act(async () => {});
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeDisabled();
  expect(screen.queryByLabelText('Длительность, мс')).not.toBeInTheDocument();
  view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    incomingContacts={makeDraft(50)} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.createFragmentPopulation.mock.calls[0][0].configuration.simulation.duration_ms).toBe(50);
});

test('submits spatially selected cells and the contact placed in the scene', async () => {
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  const candidate = body_id => ({ body_id, child_node_id: 1, edge_fraction: .5,
    isolated_root: false, conservative_clearance_um: [2, 2], recording_clearance_um: [2, 2],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } });
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate(174827), candidate(176609)] });
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [429.056, 388.5, 228.352] };
  const incoming = { kind: 'fragments', simulation,
    configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } };
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  expect(screen.queryByLabelText('STIM+ Y')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('ID клеток через запятую')).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledTimes(1));
  const payload = simulationApi.createFragmentPopulation.mock.calls[0][0];
  expect(payload.configuration.source_ids).toEqual([174827, 176609]);
  expect(payload.configuration.simulation.source_um).toEqual([429.056, 388.5, 228.352]);
  expect(payload.configuration.simulation.allow_disconnected).toBe(true);
});

test('does not submit unsupported graph or repeated cells', async () => {
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest="unknown" />);
  await act(async () => {});
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeDisabled();
  const candidate = { body_id: 1, child_node_id: 1, edge_fraction: 0.5, isolated_root: false,
    conservative_clearance_um: [2, 2], recording_clearance_um: [2, 2],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate, candidate] });
  view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('повторяющиеся нейроны');
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('stops an active calculation', async () => {
  const sceneId = '93a6be54-9021-4b67-b00b-b799240f7fce';
  const sourceId = 'd382a20d-0d63-45a6-9f3c-8295763491c5';
  sessionStorage.setItem(`simulation:pending-feedback:${sceneId}`, JSON.stringify({
    version: 1, sourceId, requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e',
  }));
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: sourceId, state: 'running' }] });
  simulationApi.cancel.mockResolvedValue({});
  const report = jest.fn();
  render(<FragmentPopulationRecording sceneRunId={sceneId} sceneManifest={graph} onPrimaryStatus={report} />);
  await waitFor(() => expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ running: true, canCancel: true })));
  await act(async () => { await report.mock.lastCall[0].cancel(); });
  expect(simulationApi.cancel).toHaveBeenCalledWith(sourceId);
});

test('automatically shows matching scene playback and requires saved event journals', async () => {
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
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  await waitFor(() => expect(show).toHaveBeenCalledWith(coupled, { source: run, restore: true }));
  expect(screen.queryByRole('button', { name: 'Показать ответ ЦНС' })).not.toBeInTheDocument();
  view.unmount(); show.mockClear();
  const incomplete = coupledRun('one');
  incomplete.result.manifest.files = [{ name: 'coupled-events.bin' }];
  simulationApi.get.mockImplementation(async id => id === 'coupled' ? incomplete : run);
  simulationApi.get.mockClear();
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  await waitFor(() => expect(simulationApi.get).toHaveBeenCalledWith('coupled', expect.anything()));
  await act(async () => {});
  expect(show).not.toHaveBeenCalled();
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
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [{ body_id: 16827, child_node_id: 1,
    edge_fraction: 0.5, isolated_root: false, conservative_clearance_um: [2, 2],
    recording_clearance_um: [2, 2], geometry: { components: 1, isolated_roots: 0,
      zero_length_edges: 0, nonpositive_radius_edges: 0 } }] });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    incomingContacts={incoming} onConsumeContacts={consume} />);
  await act(async () => {});
  expect(consume).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
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

test('uses the complete eligible geometric selection', async () => {
  const candidate = { body_id: 16827, child_node_id: 4, distance_um: 7.85, contact: 0,
    isolated_root: false, edge_fraction: 0.5, conservative_clearance_um: [7, 100],
    recording_clearance_um: [20, 100],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } };
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
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
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  await act(async () => {});
  expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled();
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [430, 387, 228] };
  view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    incomingContacts={{ kind: 'fragments', simulation,
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation } }} />);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' })); });
  expect(simulationApi.spatialCandidates).toHaveBeenCalledTimes(1);
  expect(simulationApi.spatialCandidates.mock.calls[0][1].source_um).toEqual([430, 387, 228]);
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
  fireEvent.change(screen.getByLabelText('Радиус поиска, мкм'), { target: { value: '6' } });
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
  const view = render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} incomingContacts={incoming} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.spatialCandidates).toHaveBeenCalled());
  const moved = { ...simulation, source_um: [431, ...simulation.source_um.slice(1)] };
  view.rerender(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph}
    incomingContacts={{ kind: 'fragments', simulation: moved,
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: moved } }} />);
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
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(/Слишком много подходящих клеток|не найдены подходящие реконструкции/);
  expect(simulationApi.createFragmentPopulation).not.toHaveBeenCalled();
});

test('explains unresolved synapse geometry', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error: 'executor_synapse_geometry' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Не все синапсы удалось сопоставить');
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

test('reports the number of affected cells including omitted geometry failures', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed',
    error: 'executor_synapse_geometries:174827:2:1199,176609:22:2772;omitted:3' }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('для 5 нейронов; расчёт остановлен');
  expect(screen.queryByRole('button', { name: /Исключить/ })).not.toBeInTheDocument();
});

test.each([
  'executor_synapse_geometries:174827:2:1199,174827:1:4;omitted:0',
  'executor_synapse_geometries:174827:3:2,176609:1:4;omitted:0',
  'executor_synapse_geometries:174827:1:2,176609:1:4;omitted:999',
  'executor_synapse_geometries:9223372036854775808:1:2,176609:1:4;omitted:0',
  'executor_synapse_geometry:174827:3:2',
  'executor_synapse_geometry:9223372036854775808:1:2',
])('does not present a count from malformed geometry diagnostics', async error => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error }] });
  render(<FragmentPopulationRecording sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Расчёт не завершён');
});

test('does not silently exclude a failed cell from a new spatial selection', async () => {
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', error: 'executor_synapse_geometry:174827:2:1199' }] });
  const candidate = body_id => ({ body_id, child_node_id: 1, edge_fraction: 0.5, isolated_root: false,
    conservative_clearance_um: [2, 2], recording_clearance_um: [2, 2],
    geometry: { components: 1, isolated_roots: 0, zero_length_edges: 0, nonpositive_radius_edges: 0 } });
  simulationApi.spatialCandidates.mockResolvedValue({ candidates: [candidate(174827), candidate(176609)] });
  simulationApi.createFragmentPopulation.mockResolvedValue({ id: 'new', state: 'queued' });
  render(<FragmentPopulationRecording sceneRunId="scene" sceneManifest={graph} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Нейрон 174827');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать' }));
  await waitFor(() => expect(simulationApi.createFragmentPopulation).toHaveBeenCalledWith(
    expect.objectContaining({ configuration: expect.objectContaining({ source_ids: [174827, 176609] }) })));
});
