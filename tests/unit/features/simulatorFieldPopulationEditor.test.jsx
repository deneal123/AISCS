import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import FieldPopulationEditor, { normalizeFieldPopulation } from '../../../src/features/simulator/field/FieldPopulationEditor';

test('requires unique safe positive IDs and finite source thresholds', () => {
  const cells = [{ body_id: '10438', child_node_id: '212', threshold_mv: '-20' }];
  expect(normalizeFieldPopulation(cells, ['38160'])).toEqual({ source_cells: [{ body_id: 10438, child_node_id: 212, threshold_mv: -20 }], replay_ids: [38160] });
  expect(normalizeFieldPopulation(cells, ['10438'])).toBeNull();
  expect(normalizeFieldPopulation([{ ...cells[0], body_id: '9007199254740992' }], ['2'])).toBeNull();
  expect(normalizeFieldPopulation([{ ...cells[0], threshold_mv: '' }], ['2'])).toBeNull();
  expect(normalizeFieldPopulation([{ ...cells[0], sampling_fraction: .9 }], ['2']).source_cells[0].sampling_fraction).toBe(.9);
  expect(normalizeFieldPopulation([{ ...cells[0], sampling_fraction: 1.1 }], ['2'])).toBeNull();
  expect(normalizeFieldPopulation([{ ...cells[0], morphology_sha256: 'a'.repeat(64) }], ['2']).source_cells[0].morphology_sha256).toBe('a'.repeat(64));
  expect(normalizeFieldPopulation([{ ...cells[0], morphology_sha256: 'bad' }], ['2'])).toBeNull();
});

test('editing a body id clears the morphology digest', () => {
  const change = jest.fn();
  render(<FieldPopulationEditor sources={[{ body_id: 1, child_node_id: 2, threshold_mv: -20, morphology_sha256: 'a'.repeat(64) }]}
    replay={[3]} onChange={change} />);
  fireEvent.click(screen.getByText(/Клетки модели/));
  fireEvent.change(screen.getByLabelText('ID источника 1'), { target: { value: '8' } });
  expect(change.mock.calls[0][0][0]).not.toHaveProperty('morphology_sha256');
});

test('can add and edit a second physical source', () => {
  function Harness() {
    const [state, setState] = useState({ sources: [{ body_id: 1, child_node_id: 2, threshold_mv: -20 }], replay: [3] });
    return <FieldPopulationEditor {...state} onChange={(sources, replay) => setState({ sources, replay })} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByText(/Клетки модели/));
  fireEvent.click(screen.getByRole('button', { name: 'Добавить источник' }));
  fireEvent.change(screen.getByLabelText('ID источника 2'), { target: { value: '42' } });
  expect(screen.getByLabelText('ID источника 2')).toHaveValue(42);
  fireEvent.click(screen.getByRole('button', { name: 'Удалить источник 2' }));
  expect(screen.queryByLabelText('ID источника 2')).not.toBeInTheDocument();
});

test('editing a segment discards the prior spatial selection fraction', () => {
  const change = jest.fn();
  render(<FieldPopulationEditor sources={[{ body_id: 1, child_node_id: 2, threshold_mv: -20, sampling_fraction: .9 }]}
    replay={[3]} onChange={change} />);
  fireEvent.click(screen.getByText(/Клетки модели/));
  fireEvent.change(screen.getByLabelText('Вершина SWC 1'), { target: { value: '8' } });
  expect(change.mock.calls[0][0][0]).not.toHaveProperty('sampling_fraction');
});
