import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import SimulationProgress from '../../../src/features/simulator/components/SimulationProgress';

test('shows actual stage and elapsed time without inventing an estimate', () => {
  jest.useFakeTimers();
  try {
    render(<SimulationProgress stage="Расчёт нейронов" phase={1} reducedMotion />);
    expect(screen.getByText('Этап 2 из 3 · оценка времени до конца этапа уточняется')).toBeInTheDocument();
    act(() => { jest.advanceTimersByTime(12000); });
    expect(screen.getByText('0:12')).toBeInTheDocument();
    expect(screen.getByLabelText('Точный процент расчёта недоступен')).toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});

test('reports measured work and estimates only the current phase', () => {
  jest.useFakeTimers();
  try {
    const { rerender } = render(<SimulationProgress stage="Расчёт" phase={1} reducedMotion
      progress={{ phase: 'cells', done: 1, total: 10, runId: 'run' }} />);
    act(() => { jest.advanceTimersByTime(4000); });
    rerender(<SimulationProgress stage="Расчёт" phase={1} reducedMotion
      progress={{ phase: 'cells', done: 3, total: 10, runId: 'run' }} />);
    expect(screen.getByText(/Расчёт клеток · 3 \/ 10 · 30% · до конца этапа примерно 14 с/)).toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});

test('allows stopping from the status panel when a run can be cancelled', () => {
  const cancel = jest.fn();
  render(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion onCancel={cancel} canCancel />);
  fireEvent.click(screen.getByRole('button', { name: 'Остановить' }));
  expect(cancel).toHaveBeenCalledTimes(1);
});

test('reports cells within the current feedback iteration', () => {
  const { rerender } = render(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
    progress={{ phase: 'feedback_cells', iteration: 2, done: 12, total: 46, runId: 'job' }} />);
  expect(screen.getByText(/Итерация 2 · повтор клеток · 12 \/ 46 · 26%/)).toBeInTheDocument();
  rerender(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
    progress={{ phase: 'feedback_network', iteration: 3, done: 0, total: 0, runId: 'job' }} />);
  expect(screen.getByText(/Итерация 3 · расчёт сети/)).toBeInTheDocument();
});

test('does not carry the time estimate across feedback iterations', () => {
  jest.useFakeTimers();
  try {
    const { rerender } = render(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
      progress={{ phase: 'feedback_cells', iteration: 1, done: 1, total: 46, runId: 'job' }} />);
    act(() => { jest.advanceTimersByTime(4000); });
    rerender(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
      progress={{ phase: 'feedback_cells', iteration: 1, done: 3, total: 46, runId: 'job' }} />);
    expect(screen.getByText(/до конца этапа примерно/)).toBeInTheDocument();
    rerender(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
      progress={{ phase: 'feedback_cells', iteration: 2, done: 4, total: 46, runId: 'job' }} />);
    expect(screen.getByText(/оценка времени до конца этапа уточняется/)).toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});

test('shows field preparation at zero percent and its verification stage', () => {
  const { rerender } = render(<SimulationProgress stage="Расчёт поля" phase={1} reducedMotion
    progress={{ phase: 'field', done: 0, total: 166700, runId: 'job' }} />);
  expect(screen.getByText(/Расчёт поля · 0 \/ 166700 · 0%/)).toBeInTheDocument();
  rerender(<SimulationProgress stage="Расчёт поля" phase={1} reducedMotion
    progress={{ phase: 'field_verification', done: 0, total: 0, runId: 'job' }} />);
  expect(screen.getByText(/Проверка рассчитанного поля/)).toBeInTheDocument();
});

test('reports completed network ticks as model time and estimates only this stage', () => {
  jest.useFakeTimers();
  try {
    const { rerender } = render(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
      progress={{ phase: 'network', done: 0, total: 100, runId: 'job' }} />);
    expect(screen.getByText(/Расчёт сети · модельное время · 0 \/ 100 мс · 0%/)).toBeInTheDocument();
    act(() => { jest.advanceTimersByTime(4000); });
    rerender(<SimulationProgress stage="Расчёт сети" phase={2} reducedMotion
      progress={{ phase: 'network', done: 20, total: 100, runId: 'job' }} />);
    expect(screen.getByText(/20 \/ 100 мс · 20% · до конца этапа примерно 16 с/)).toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});
