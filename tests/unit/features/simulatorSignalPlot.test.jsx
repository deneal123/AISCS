import React from 'react';
import { render, screen } from '@testing-library/react';
import SignalPlot from '../../../src/features/simulator/recording/SignalPlot';
import { scenePlayback } from '../../../src/features/simulator/recording/scenePlayback';

let context;
beforeEach(() => {
  context = { setTransform: jest.fn(), fillText: jest.fn(), beginPath: jest.fn(),
    moveTo: jest.fn(), lineTo: jest.fn(), stroke: jest.fn(), clearRect: jest.fn(),
    drawImage: jest.fn(), measureText: jest.fn(() => ({ width: 20 })) };
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context);
  jest.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect')
    .mockReturnValue({ width: 800, height: 184, left: 0 });
  global.ResizeObserver = class { observe() {} disconnect() {} };
});
afterEach(() => { jest.restoreAllMocks(); delete global.ResizeObserver; });

test('fast mode displays the actual STIM current and identifies the absent recording', () => {
  const stimulusSegments = [];
  context.lineTo.mockImplementation((x, y) => {
    if (context.strokeStyle === '#EAA064') stimulusSegments.push([x, y]);
  });
  const run = { configuration: { waveform: [0, 1, 0], current_na: -300 }, result: {
    manifest: { kind: 'experimental-field-proxy' },
    preview: { duration_ms: 3, spikes_by_ms: [0, 1, 0, 0] },
  } };
  const preview = scenePlayback({ activeField: run, sceneField: run, direct: true });
  render(<SignalPlot preview={preview} timeMs={0} onTime={() => {}} showResponse />);
  expect(context.fillText).toHaveBeenCalledWith('-300', 65, 12);
  expect(stimulusSegments).toHaveLength(5);
  expect(stimulusSegments[0][0]).toBeCloseTo(stimulusSegments[1][0]);
  expect(stimulusSegments[2][0]).toBeCloseTo(stimulusSegments[3][0]);
  expect(stimulusSegments[0][1]).not.toEqual(stimulusSegments[1][1]);
  expect(context.fillText).not.toHaveBeenCalledWith('Сигнал STIM недоступен', expect.anything(), expect.anything());
  expect(context.fillText).toHaveBeenCalledWith('Запись E1–REF не рассчитана', expect.anything(), expect.anything());
  expect(screen.getByRole('img')).toHaveAccessibleName(/запись E1 относительно REF не рассчитана/);
  expect(screen.getByRole('img')).toHaveAccessibleDescription(/Запись E1−REF в этом режиме не рассчитана/);
  expect(screen.getByRole('img')).toHaveAccessibleDescription(/усреднённый за 1 мс ток/);
});

test('missing stimulus current is not converted into a fictitious zero', () => {
  const preview = { time_ms: [0, 1], signal_uv: null, networkOnly: true, electrical: true,
    stimulus_current_na: null, stimulus_fraction: [0], stimulus_time_ms: [.5], connectome: {} };
  render(<SignalPlot preview={preview} timeMs={0} onTime={() => {}} showResponse />);
  expect(context.fillText).toHaveBeenCalledWith('Сигнал STIM недоступен', expect.anything(), expect.anything());
  expect(screen.getByRole('img')).toHaveAccessibleDescription(/Ток воздействия недоступен/);
});

test('an explicit zero current remains a valid control', () => {
  const run = { configuration: { waveform: [0], current_na: 0 }, result: {
    manifest: { kind: 'experimental-field-proxy' }, preview: { duration_ms: 1, spikes_by_ms: [0, 0] },
  } };
  const preview = scenePlayback({ activeField: run, sceneField: run, direct: true });
  render(<SignalPlot preview={preview} timeMs={0} onTime={() => {}} showResponse />);
  expect(context.fillText).toHaveBeenCalledWith('0', 65, 12);
  expect(context.fillText).not.toHaveBeenCalledWith('Сигнал STIM недоступен', expect.anything(), expect.anything());
});
