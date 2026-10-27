import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import TraceEventRow from '../../../src/features/chat/components/trace/TraceEventRow';

describe('TraceEventRow props contract', () => {
  it('не обрезает заголовок и пояснение ошибки', () => {
    const detail = 'Сервис временно недоступен. '.repeat(30);
    render(<ChakraProvider><TraceEventRow event={{ kind: 'error',
      title: 'Ошибка канала обработки', detail }} /></ChakraProvider>);
    const title = screen.getByText('Ошибка канала обработки');
    const description = screen.getByText(detail.trim());
    expect(getComputedStyle(title).webkitLineClamp || '').toBe('');
    expect(getComputedStyle(description).webkitLineClamp || '').toBe('');
  });
  it('uses Russian 24-hour time regardless of the browser locale', () => {
    const format = jest.spyOn(Date.prototype, 'toLocaleTimeString');
    try {
      render(
        <ChakraProvider>
          <TraceEventRow event={{ title: 'Этап', kind: 'info',
            timestamp: new Date(2026, 9, 4, 21, 7).toISOString() }} />
        </ChakraProvider>
      );
      expect(screen.getByText('21:07')).toBeInTheDocument();
      expect(format).toHaveBeenCalledWith('ru-RU', {
        hour: '2-digit', minute: '2-digit', hour12: false,
      });
    } finally {
      format.mockRestore();
    }
  });
  it('renders title and detail for event prop', () => {
    render(
      <ChakraProvider>
        <TraceEventRow event={{ id: 'e1', title: 'Step title', detail: 'Step detail', kind: 'info', timestamp: '2026-04-22T10:00:00Z' }} eventIndex={1} />
      </ChakraProvider>
    );

    expect(screen.getByText('Step title')).toBeInTheDocument();
    expect(screen.getByText('Step detail')).toBeInTheDocument();
  });
});
