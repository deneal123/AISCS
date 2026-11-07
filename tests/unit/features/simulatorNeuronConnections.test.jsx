import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import NeuronConnections from '../../../src/features/simulator/connectome/NeuronConnections';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { outgoing: jest.fn(), incoming: jest.fn(), populationTargetCandidates: jest.fn(), populationTargetRuns: jest.fn().mockResolvedValue({ items: [] }) } }));

test('shows modelled incoming events only for the selected saved electrical run', async () => {
  simulationApi.outgoing.mockResolvedValue({ total: 0, items: [], next_offset: null });
  simulationApi.populationTargetCandidates.mockResolvedValue({ candidates: [{ source_id: 75508, events: 2, first_tick_ms: 4 }] });
  render(<NeuronConnections runId="graph" fragmentRunId="electrical" nodeId="18669" onClose={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить входящие события' }));
  expect(await screen.findByText(/Нейрон 75508: 2, первое — 4 мс/)).toBeInTheDocument();
  expect(screen.getByText(/геометрия и физиология связей требуют проверки/i)).toBeInTheDocument();
  expect(simulationApi.populationTargetCandidates).toHaveBeenCalledWith('electrical', '18669', expect.any(AbortSignal));
});

test('shows bounded results and fetches the next page', async () => {
  simulationApi.outgoing.mockImplementation(async (_run, _node, offset) => ({
    total: 21, next_offset: offset ? null : 20,
    items: [{ target_id: offset ? '999' : '123', synapse_count: 4, model_sign: -1 }],
  }));
  render(<NeuronConnections runId="run" nodeId="100" onClose={() => {}} />);
  expect(await screen.findByText(/Исходящих связей: 21/)).toBeInTheDocument();
  expect(screen.getByText(/→ 123/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }));
  expect(await screen.findByText(/→ 999/)).toBeInTheDocument();
  expect(simulationApi.outgoing).toHaveBeenCalledWith('run', '100', 20, expect.any(AbortSignal));
});

test('reports failures and retries the same query', async () => {
  simulationApi.outgoing.mockReset().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ total: 0, items: [], next_offset: null });
  render(<NeuronConnections runId="run" nodeId="100" onClose={() => {}} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить связи.');
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByText('На этой странице связей нет.')).toBeInTheDocument();
});

test('incoming links show the source neuron and reset pagination', async () => {
  simulationApi.outgoing.mockResolvedValue({ total: 0, items: [], next_offset: null });
  simulationApi.incoming.mockResolvedValue({ total: 1, items: [{ source_id: '314', synapse_count: 6, model_sign: 1 }], next_offset: null });
  render(<NeuronConnections runId="run" nodeId="100" onClose={() => {}} />);
  await screen.findByText('На этой странице связей нет.');
  fireEvent.click(screen.getByRole('button', { name: 'Входящие' }));
  expect(await screen.findByText(/Входящих связей: 1/)).toBeInTheDocument();
  expect(screen.getByText(/← 314/)).toBeInTheDocument();
  expect(simulationApi.incoming).toHaveBeenCalledWith('run', '100', 0, expect.any(AbortSignal));
});

test('a connection opens the exact neighboring neuron', async () => {
  const select = jest.fn();
  simulationApi.outgoing.mockResolvedValue({ total: 1, next_offset: null,
    items: [{ target_id: '9007199254740993', synapse_count: 2, model_sign: 1 }] });
  render(<NeuronConnections runId="run" nodeId="100" onClose={() => {}} onSelectNode={select} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Открыть нейрон 9007199254740993' }));
  expect(select).toHaveBeenCalledWith('9007199254740993');
});
