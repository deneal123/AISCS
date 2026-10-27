import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatMessagesArea from '@features/chat/components/ChatMessagesArea';

jest.mock('@features/chat/components/ChatMessageItem', () => () => <div>Сообщение документа</div>);
jest.mock('@features/chat/components/ChatEmptyState', () => () => <div>Кем мне быть?</div>);

const props = {
  atBottom: true, visibleMessages: [], providerStatus: {}, traceSessionByAnchor: new Map(),
};

it('отделяет следующую реплику пользователя от завершившейся панели ошибки', () => {
  const visibleMessages = ['first', 'next'].map(id => ({ id, type: 'user', content: id,
    timestamp: '2026-10-24T19:05:00Z' }));
  render(<ChakraProvider><ChatMessagesArea {...props} visibleMessages={visibleMessages}
    showTracePanel traceSessionByAnchor={new Map([['first', {
      id: 'failed', status: 'error', events: [],
    }]])} tracePanelsExpanded={{}} onTraceToggle={jest.fn()} /></ChakraProvider>);
  expect(screen.getAllByText('Сообщение документа')[1].parentElement).toHaveStyle({ marginTop: '16px' });
});

it('keeps the PDF assistant empty without hiding normal Chat onboarding', () => {
  const view = render(<ChakraProvider><ChatMessagesArea {...props} documentMode /></ChakraProvider>);
  expect(screen.queryByText('Кем мне быть?')).not.toBeInTheDocument();
  view.rerender(<ChakraProvider><ChatMessagesArea {...props} /></ChakraProvider>);
  expect(screen.getByText('Кем мне быть?')).toBeInTheDocument();
  view.rerender(<ChakraProvider><ChatMessagesArea {...props} documentMode /></ChakraProvider>);
  expect(screen.queryByText('Кем мне быть?')).not.toBeInTheDocument();
});

it('retains history failure recovery in the quiet PDF assistant', () => {
  render(<ChakraProvider><ChatMessagesArea {...props} documentMode historyError /></ChakraProvider>);
  expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  expect(screen.queryByText('Кем мне быть?')).not.toBeInTheDocument();
});
