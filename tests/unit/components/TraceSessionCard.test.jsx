import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChakraProvider } from '@chakra-ui/react';
import TraceSessionCard from '../../../src/features/chat/components/trace/TraceSessionCard';

describe('TraceSessionCard props contract', () => {
  it.each([[1, '1 шаг'], [3, '3 шага'], [12, '12 шагов'], [21, '21 шаг']])(
    'показывает корректный счётчик для %i этапов ошибки', (count, label) => {
      render(<ChakraProvider><TraceSessionCard isExpanded onToggleExpanded={jest.fn()}
        session={{ id: 'failed', status: 'error', events: Array.from({ length: count }, (_, id) => ({
          id: String(id), kind: 'error', title: `Ошибка ${id}`, detail: 'Сообщение сохранено.',
        })) }} /></ChakraProvider>);
      expect(screen.getByText(label)).toBeInTheDocument();
    },
  );
  it('направляет Home/End в скроллер, не перехватывая клавиши его потомков', () => {
    render(<ChakraProvider><TraceSessionCard layout="workbench" isExpanded
      session={{ id: 'keys', status: 'done', events: [{ id: 'one', kind: 'info', title: 'Шаг' }] }}
      onToggleExpanded={jest.fn()} /></ChakraProvider>);
    const scroll = screen.getByRole('region', { name: 'Этапы выполнения' });
    Object.defineProperty(scroll, 'scrollHeight', { value: 1000 });
    fireEvent.keyDown(scroll, { key: 'End' });
    expect(scroll.scrollTop).toBe(1000);
    fireEvent.keyDown(within(scroll).getByText('Шаг'), { key: 'Home' });
    expect(scroll.scrollTop).toBe(1000);
    fireEvent.keyDown(scroll, { key: 'Home' });
    expect(scroll.scrollTop).toBe(0);
  });
  it('contains workbench scrolling below its fixed header and keeps every step readable', () => {
    render(<ChakraProvider><TraceSessionCard layout="workbench"
      session={{ id: 'bounded', status: 'running', events: Array.from({ length: 30 }, (_, i) => ({
        id: `e${i}`, kind: 'info', title: `Шаг ${i + 1}`, detail: 'Подробности шага',
      })) }} isExpanded onToggleExpanded={jest.fn()} /></ChakraProvider>);
    const scroll = screen.getByRole('region', { name: 'Этапы выполнения' });
    expect(scroll).toHaveAttribute('tabindex', '0');
    expect(scroll).toHaveStyle({ overflowY: 'auto' });
    expect(parseFloat(getComputedStyle(scroll).minHeight)).toBe(0);
    expect(within(scroll).getByText('Шаг 30')).toBeInTheDocument();
    expect(within(scroll).queryByRole('button', { name: /Ход работы/ })).not.toBeInTheDocument();
    expect(screen.getByTestId('workbench-trace-card')).toHaveStyle({ overflow: 'hidden' });
  });

  it('does not turn the ordinary Chat trace into a nested scrolling panel', () => {
    render(<ChakraProvider><TraceSessionCard session={{ id: 'chat', status: 'done', events: [] }}
      isExpanded onToggleExpanded={jest.fn()} /></ChakraProvider>);
    expect(screen.queryByRole('region', { name: 'Этапы выполнения' })).not.toBeInTheDocument();
  });

  it('keeps a financial decision reachable when workbench steps are collapsed', () => {
    render(<ChakraProvider><TraceSessionCard layout="workbench" isExpanded={false} onRunMode={jest.fn()}
      onToggleExpanded={jest.fn()} session={{ id: 'offer', status: 'awaiting_confirmation', events: [{
        id: 'offer-event', kind: 'offer', offer: { offer_id: 'offer', mode: 'deep_research', label: 'Исследование', offer_kind: 'tool', blocking: true,
          offered_at: new Date().toISOString(), expires_in_sec: 60 },
      }] }} /></ChakraProvider>);
    const scroll = screen.getByRole('region', { name: 'Этапы выполнения' });
    expect(within(scroll).getByRole('button', { name: 'Использовать', exact: true })).toBeVisible();
  });
  it('shows the actual video stage even when collapsed, without a fake percentage', () => {
    render(<ChakraProvider><TraceSessionCard
      session={{ id: 'video', status: 'running', startedAt: new Date().toISOString(), events: [],
        progress: { label: 'Загружаю видео', percent: null } }}
      isExpanded={false} onToggleExpanded={jest.fn()}
    /></ChakraProvider>);
    expect(screen.getByText('Загружаю видео')).toBeVisible();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'false');
  });
  it('calls onToggleExpanded when header is toggled', async () => {
    const onToggleExpanded = jest.fn();
    render(
      <ChakraProvider>
        <TraceSessionCard
          session={{ id: 's1', title: 'Query', status: 'running', events: [] }}
          isCompactTrace={false}
          isExpanded={true}
          onToggleExpanded={onToggleExpanded}
        />
      </ChakraProvider>
    );

    await userEvent.click(screen.getByRole('button'));
    expect(onToggleExpanded).toHaveBeenCalled();
  });
});
