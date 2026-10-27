import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ContextGauge from '../../../src/features/chat/components/composer/ContextGauge';

const wrapper = ({ children }) => <ChakraProvider>{children}</ChakraProvider>;
const advance = () => act(() => jest.advanceTimersByTime(250));
beforeEach(() => jest.useFakeTimers());
afterEach(() => { cleanup(); jest.clearAllTimers(); jest.useRealTimers(); });

it('does not open a pending focus hint after the compaction click', () => {
  const compact = jest.fn();
  render(<ContextGauge pct={1} onCompact={compact} />, { wrapper });
  const trigger = screen.getByRole('button', { name: /Контекст заполнен/ });
  fireEvent.focus(trigger);
  fireEvent.click(trigger);
  advance();
  expect(compact).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});

it('retains hints for a fresh keyboard focus after activation', () => {
  render(<ContextGauge pct={1} onCompact={() => {}} />, { wrapper });
  const trigger = screen.getByRole('button', { name: /Контекст заполнен/ });
  fireEvent.focus(trigger);
  fireEvent.click(trigger);
  advance();
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.blur(trigger);
  fireEvent.focus(trigger);
  advance();
  expect(screen.getByRole('tooltip')).toBeInTheDocument();
});

it('does not resurrect the activated hint when compaction finishes', () => {
  const view = render(<ContextGauge pct={10} onCompact={() => {}} />, { wrapper });
  const trigger = screen.getByRole('button', { name: /Контекст заполнен/ });
  fireEvent.focus(trigger);
  fireEvent.click(trigger);
  view.rerender(<ContextGauge pct={10} busy onCompact={() => {}} />);
  advance();
  view.rerender(<ContextGauge pct={1} onCompact={() => {}} />);
  advance();
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});
