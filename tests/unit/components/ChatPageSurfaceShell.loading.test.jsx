import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatPageSurfaceShell from '@features/chat/components/ChatPageSurfaceShell';

jest.mock('@features/workspace-room', () => {
  const pending = new Promise(() => {});
  return { WorkHub: () => { throw pending; }, IdeStudio: () => { throw pending; } };
});
jest.mock('@features/chat/components/ChatHeaderBar', () => ({ onSurfaceChange }) => (
  <button onClick={() => onSurfaceChange('chat')}>Чат</button>
));
jest.mock('@features/chat/components/ChatMessagesArea', () => () => <div>Сообщения чата</div>);
jest.mock('@features/chat/components/composer/ChatComposerPanel', () => () => <div>Поле сообщения</div>);

it('announces lazy Work loading without blocking the existing Chat navigation', async () => {
  const onSurfaceChange = jest.fn();
  await act(async () => render(<ChakraProvider>
    <ChatPageSurfaceShell
      sidebar={{ collapsed: true, render: () => null }}
      header={{ onSurfaceChange, surface: 'work' }}
      work={{ mounted: true, active: true, props: {} }}
      chat={{ messages: {}, composer: {} }}
    />
  </ChakraProvider>));
  expect(screen.getByRole('status')).toHaveTextContent('Загружаю рабочее место');
  expect(screen.getByRole('status')).not.toHaveTextContent('%');
  fireEvent.click(screen.getByRole('button', { name: 'Чат' }));
  expect(onSurfaceChange).toHaveBeenCalledWith('chat');
});

it('shows a dismissible Library pending drawer even while Work is hidden behind Chat', async () => {
  const close = jest.fn();
  await act(async () => render(<ChakraProvider><ChatPageSurfaceShell
    sidebar={{ collapsed: true, render: () => null }} header={{ surface: 'chat' }}
    work={{ mounted: true, active: false, props: { libraryOpen: true, onLibraryClose: close } }}
    chat={{ messages: {}, composer: {} }} /></ChakraProvider>));
  expect(screen.getByRole('dialog', { name: 'Библиотека' })).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Загружаю библиотеку');
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть библиотеку' }));
  expect(close).toHaveBeenCalledTimes(1);
});
