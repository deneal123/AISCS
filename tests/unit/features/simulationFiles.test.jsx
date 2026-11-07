import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SimulationFiles, { simulationFileGroups } from '../../../src/features/simulator/recording/SimulationFiles';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  artifacts: jest.fn(), download: jest.fn(), downloadManifest: jest.fn(),
} }));
jest.mock('@shared/hooks/useAppToast', () => ({ useAppToast: () => jest.fn() }));

const graph = 'graph';
const scene = { id: 'scene', state: 'completed', result: { preview: { connectome: { manifest_sha256: graph } } } };
const source = { id: 'source', state: 'completed', parent_run_id: 'scene', configuration: { graph_manifest_sha256: graph } };
const coupled = { id: 'coupled', state: 'completed', parent_run_id: 'source', configuration: { graph_manifest_sha256: graph } };
const proxy = { id: 'proxy', state: 'completed', parent_run_id: 'source', configuration: { graph_manifest_sha256: graph } };

beforeEach(() => {
  jest.resetAllMocks();
  simulationApi.artifacts.mockImplementation(async id => ({ items: [{ id: `${id}-file`, name: `${id}.csv`,
    bytes: 12, sha256: 'a'.repeat(64) }] }));
  simulationApi.download.mockResolvedValue();
  simulationApi.downloadManifest.mockResolvedValue();
});

test('downloads the actual field and source artifacts from their own runs', async () => {
  render(<SimulationFiles scene={scene} playback={{ sceneRunId: 'scene', run: coupled, source, proxy }} />);
  const recording = await screen.findByRole('region', { name: 'Запись и обратная связь' });
  expect(await within(recording).findByText('coupled.csv')).toBeInTheDocument();
  expect(await screen.findByText('source.csv')).toBeInTheDocument();
  expect(await screen.findByText('proxy.csv')).toBeInTheDocument();
  expect(await screen.findByText('scene.csv')).toBeInTheDocument();
  fireEvent.click(within(recording).getByRole('button', { name: 'Скачать coupled.csv' }));
  await waitFor(() => expect(simulationApi.download).toHaveBeenCalledWith('coupled', expect.objectContaining({ id: 'coupled-file' })));
  fireEvent.click(within(recording).getByRole('button', { name: 'Манифест' }));
  await waitFor(() => expect(simulationApi.downloadManifest).toHaveBeenCalledWith('coupled'));
});

test('direct calculation is grouped with its scene; foreign results are excluded', () => {
  const direct = { ...proxy, parent_run_id: 'scene' };
  expect(simulationFileGroups(scene, { sceneRunId: 'scene', direct: true, run: direct })
    .map(group => group.run.id)).toEqual(['proxy', 'scene']);
  expect(simulationFileGroups(scene, { sceneRunId: 'other', run: coupled, source, proxy })
    .map(group => group.run.id)).toEqual(['scene']);
  expect(simulationFileGroups(scene, { sceneRunId: 'scene', run: coupled,
    source: { ...source, parent_run_id: 'other' }, proxy }).map(group => group.run.id)).toEqual(['scene']);
});

test('keeps completed cell artifacts available after feedback failed, without crossing scenes', () => {
  const saved = { sceneRunId: 'scene', source };
  expect(simulationFileGroups(scene, null, null, saved).map(group => group.run.id)).toEqual(['source', 'scene']);
  expect(simulationFileGroups(scene, null, null, { ...saved, sceneRunId: 'other' })
    .map(group => group.run.id)).toEqual(['scene']);
  const direct = { ...proxy, parent_run_id: 'scene' };
  expect(simulationFileGroups(scene, { sceneRunId: 'scene', direct: true, run: direct }, null, saved)
    .map(group => group.run.id)).toEqual(['proxy', 'scene']);
});

test('includes a matching additional recording and excludes one with a different parent', () => {
  const recorded = { ...coupled, configuration: { graph_manifest_sha256: graph, source_ids: [1] },
    result: { preview: { time_ms: [0, 1] } } };
  const target = { id: 'target', state: 'completed', parent_run_id: 'coupled',
    configuration: { graph_manifest_sha256: graph, target_id: '42' },
    result: { preview: { time_ms: [0, 1], neural_uv: [0, .1], source_cells: 1, target_id: '42' } } };
  const playback = { sceneRunId: 'scene', run: recorded, source, proxy };
  expect(simulationFileGroups(scene, playback, target).map(group => group.run.id))
    .toEqual(['target', 'coupled', 'proxy', 'source', 'scene']);
  expect(simulationFileGroups(scene, playback, { ...target, parent_run_id: 'other' }).map(group => group.run.id))
    .toEqual(['coupled', 'proxy', 'source', 'scene']);
});

test('discards delayed files after switching scenes', async () => {
  let finish;
  simulationApi.artifacts.mockImplementation(id => id === 'scene'
    ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({ items: [{ id: 'new', name: 'new.csv', bytes: 1, sha256: 'a'.repeat(64) }] }));
  const view = render(<SimulationFiles scene={scene} />);
  await waitFor(() => expect(finish).toBeDefined());
  view.rerender(<SimulationFiles scene={{ ...scene, id: 'new-scene' }} />);
  expect(await screen.findByText('new.csv')).toBeInTheDocument();
  finish({ items: [{ id: 'stale', name: 'stale.csv', bytes: 1, sha256: 'a'.repeat(64) }] });
  expect(screen.queryByText('stale.csv')).not.toBeInTheDocument();
});
