import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Recording from '../../../src/features/simulator/recording/FragmentPopulationRecording';
import { simulationApi } from '../../../src/features/simulator/api';
import useFullPopulationFeedback from '../../../src/features/simulator/recording/useFullPopulationFeedback';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  fragmentPopulationRuns: jest.fn(), feedbackRuns: jest.fn(), contactPositions: jest.fn(),
} }));
jest.mock('../../../src/features/simulator/recording/useFullPopulationFeedback', () => jest.fn());
jest.mock('../../../src/features/simulator/recording/useDirectNetworkProxy', () => () => ({ status: 'idle' }));
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
  useFullPopulationFeedback.mockImplementation(callback => {
    complete = callback;
    return { start, status: 'idle', running: false };
  });
});

test('full calculation submits four current contacts and displays matching result', async () => {
  const show = jest.fn();
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} onShowOnBody={show} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'full' } });
  await act(async () => fireEvent.submit(view.container.querySelector('form')));
  expect(start).toHaveBeenCalledWith(expect.objectContaining({ graph_manifest_sha256: graph,
    simulation: expect.objectContaining({ source_um: expect.any(Array), return_um: expect.any(Array),
      electrode_um: expect.any(Array), reference_um: expect.any(Array), pulse_count: null,
      pulse_interval_ms: null }) }), expect.objectContaining({ signature: expect.any(String) }));
  expect(simulationApi.contactPositions).toHaveBeenCalledWith('scene', expect.objectContaining({
    positions_um: expect.arrayContaining([expect.any(Array), expect.any(Array), expect.any(Array), expect.any(Array)]),
  }), expect.any(AbortSignal));
  act(() => complete({ id: 'result', configuration: { graph_manifest_sha256: graph } }));
  expect(show).toHaveBeenCalledWith(expect.objectContaining({ id: 'result' }), {});
});

test('full calculation is not submitted when a contact intersects morphology', async () => {
  simulationApi.contactPositions.mockResolvedValue({ potential_intersections: [{ contact_indices: [2] }] });
  const view = render(<Recording sceneRunId="scene" sceneManifest={graph} />);
  await waitFor(() => expect(simulationApi.fragmentPopulationRuns).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.change(screen.getByLabelText('Режим расчёта'), { target: { value: 'full' } });
  await act(async () => fireEvent.submit(view.container.querySelector('form')));
  expect(start).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Контакты слишком близко');
});
