import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Recording from '../../../src/features/simulator/recording/FragmentPopulationRecording';
import { fieldDemoPreset } from '../../../src/features/simulator/field/fieldDemoPreset';
import { simulationApi } from '../../../src/features/simulator/api';
import useDirectNetworkProxy from '../../../src/features/simulator/recording/useDirectNetworkProxy';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  fragmentPopulationRuns: jest.fn(), feedbackRuns: jest.fn(), contactPositions: jest.fn(),
} }));
jest.mock('../../../src/features/simulator/recording/useDirectNetworkProxy', () => jest.fn());
jest.mock('../../../src/features/simulator/recording/useWholeNetworkProxy', () => () => ({ status: 'idle' }));
jest.mock('@shared/controls/AppSelect', () => ({ ariaLabel, value, onChange, options, isDisabled }) => (
  <select aria-label={ariaLabel} value={value} disabled={isDisabled} onChange={event => onChange(event.target.value)}>
    {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select>
));

const graph = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';
const start = jest.fn();
let complete;
beforeEach(() => {
  jest.resetAllMocks(); sessionStorage.clear();
  simulationApi.fragmentPopulationRuns.mockResolvedValue({ items: [] });
  simulationApi.feedbackRuns.mockResolvedValue({ items: [] });
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [] });
  useDirectNetworkProxy.mockImplementation(callback => {
    complete = callback;
    return { start, status: 'idle', running: false };
  });
  global.crypto = { randomUUID: () => 'fba50b24-f408-4d70-bd9b-3f0e18f76412' };
});

async function launch(view) {
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'fast' } });
  await act(async () => fireEvent.submit(view.container.querySelector('form')));
  expect(start).toHaveBeenCalledTimes(1);
  return start.mock.calls[0][1].simulation;
}

test('an unchanged fast run displays its completed result', async () => {
  const show = jest.fn();
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  const simulation = await launch(view);
  act(() => complete({ id: 'finished' }, simulation));
  expect(show).toHaveBeenCalledWith({ id: 'finished' }, { direct: true, simulation });
});

test('a late fast result cannot replace contacts edited during calculation', async () => {
  const show = jest.fn();
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  const simulation = await launch(view);
  const moved = { ...simulation, source_um: [123, 124, 125] };
  view.rerender(<Recording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show}
    incomingContacts={{ kind: 'fragments', simulation: moved,
      configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation: moved } }} />);
  await act(async () => {});
  act(() => complete({ id: 'finished' }, simulation));
  expect(show).not.toHaveBeenCalled();
});

test('changing current marks the current scene as a new draft with the same four contacts', async () => {
  const show = jest.fn(), adjust = jest.fn();
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show}
    onAdjustParameters={adjust} />);
  const simulation = await launch(view);
  act(() => complete({ id: 'finished' }, simulation));
  expect(show).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText('Ток STIM, нА'), { target: { value: '-450' } });
  expect(adjust).toHaveBeenCalledTimes(1);
  const draft = adjust.mock.calls[0][0];
  expect(draft.simulation.current_na).toBe(-450);
  for (const key of ['source_um', 'return_um', 'electrode_um', 'reference_um']) {
    expect(draft.simulation[key]).toEqual(simulation[key]);
  }
  expect(draft.configuration.simulation).toEqual(draft.simulation);
  act(() => complete({ id: 'late' }, simulation));
  expect(show).toHaveBeenCalledTimes(1);
});

test('a restored fast result cannot override an already edited scene', async () => {
  const show = jest.fn();
  render(<Recording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} canRestore={() => false} />);
  await act(async () => {});
  act(() => complete({ id: 'old' }, fieldDemoPreset(graph).simulation));
  expect(show).not.toHaveBeenCalled();
});

test('screens only stimulating contacts before starting a fast full-network run', async () => {
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [{ contact_indices: [0] }] });
  const failure = jest.fn();
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onFailure={failure} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'fast' } });
  await act(async () => fireEvent.submit(view.container.querySelector('form')));
  expect(simulationApi.contactPositions).toHaveBeenCalledWith('scene', expect.objectContaining({
    positions_um: [expect.any(Array), expect.any(Array)], clearance_um: expect.any(Number),
  }), expect.any(AbortSignal));
  expect(screen.getByRole('alert')).toHaveTextContent('STIM+');
  expect(start).not.toHaveBeenCalled();
  expect(failure).toHaveBeenCalledTimes(1);
});

test('a failed contact check does not enqueue the fast network calculation', async () => {
  simulationApi.contactPositions.mockRejectedValue(new Error('unavailable'));
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'fast' } });
  await act(async () => fireEvent.submit(view.container.querySelector('form')));
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось проверить контакты');
  expect(start).not.toHaveBeenCalled();
});

test('rejects an invalid contact-screen response instead of treating it as clear', async () => {
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [{ contact_indices: [] }] });
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'fast' } });
  await act(async () => fireEvent.submit(view.container.querySelector('form')));
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось проверить контакты');
  expect(start).not.toHaveBeenCalled();
});

test('cancelling the fast-mode contact check never enqueues a calculation', async () => {
  let finish;
  simulationApi.contactPositions.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const status = jest.fn();
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onPrimaryStatus={status} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'fast' } });
  fireEvent.submit(view.container.querySelector('form'));
  await waitFor(() => expect(status).toHaveBeenLastCalledWith(expect.objectContaining({
    running: true, stage: 'Проверка контактов', canCancel: true,
  })));
  const signal = simulationApi.contactPositions.mock.calls[0][2];
  await act(async () => status.mock.calls.at(-1)[0].cancel());
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ potential_intersections: [] }));
  expect(start).not.toHaveBeenCalled();
});

test('moving a contact during fast preflight requires a new launch', async () => {
  let finish;
  simulationApi.contactPositions.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'fast' } });
  fireEvent.submit(view.container.querySelector('form'));
  await waitFor(() => expect(finish).toBeDefined());
  const simulation = { ...fieldDemoPreset(graph).simulation, source_um: [123, 124, 125] };
  view.rerender(<Recording sceneRunId="scene" sceneManifest={graph} incomingContacts={{
    kind: 'fragments', simulation, configuration: { graph_manifest_sha256: graph, source_ids: [1], simulation },
  }} />);
  await act(async () => finish({ potential_intersections: [] }));
  expect(start).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('изменились во время проверки');
});
