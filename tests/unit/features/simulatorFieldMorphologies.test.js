import { renderHook, waitFor } from '@testing-library/react';
import useFieldMorphologies from '../../../src/features/simulator/field/useFieldMorphologies';
import { simulationApi } from '../../../src/features/simulator/api';
import { decodeSelectedMorphology } from '../../../src/features/simulator/connectome/selectedMorphology';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { morphology: jest.fn() } }));
jest.mock('../../../src/features/simulator/connectome/selectedMorphology', () => ({ decodeSelectedMorphology: jest.fn() }));

beforeEach(() => jest.resetAllMocks());

test('reports missing morphology and keeps only verified cells', async () => {
  simulationApi.morphology.mockImplementation(async (_run, id) => {
    if (id === '2') throw new Error('unavailable');
    return { id };
  });
  decodeSelectedMorphology.mockImplementation(async record => ({ positions: [record.id] }));
  const { result } = renderHook(() => useFieldMorphologies('run', ['1', '2', '3'], 'manifest'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.data.map(cell => cell.id)).toEqual(['1', '3']);
  expect(result.current.missing).toEqual(['2']);
  expect(simulationApi.morphology.mock.calls.map(call => call[1])).toEqual(['1', '2', '3']);
});

test('changing the run suppresses results of an older request', async () => {
  let finish;
  simulationApi.morphology.mockImplementation((run) => run === 'old'
    ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({ id: 'new' }));
  decodeSelectedMorphology.mockImplementation(async record => ({ positions: [record.id] }));
  const { result, rerender } = renderHook(({ run }) => useFieldMorphologies(run, ['1'], 'manifest'), { initialProps: { run: 'old' } });
  rerender({ run: 'new' });
  await waitFor(() => expect(result.current.data[0]?.positions).toEqual(['new']));
  finish({ id: 'old' });
  await Promise.resolve();
  expect(result.current.data[0].positions).toEqual(['new']);
});
