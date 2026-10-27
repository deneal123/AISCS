import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkbenchLibraryDrawer } from '@features/workspace-room/components/WorkbenchLibraryDrawer';
import { getAccountWorkLibrary } from '@api/chat';

jest.mock('@api/chat', () => ({ getAccountWorkLibrary: jest.fn() }));
beforeEach(() => {
  jest.clearAllMocks();
  getAccountWorkLibrary.mockResolvedValue({ state: 'ready', items: [{
    file_id: 'owned-file', name: 'notes.md', availability: 'ready',
  }], next_offset: 10 });
});

it('сохраняет файлы при ошибке следующей страницы и позволяет повторить чтение', async () => {
  render(<ChakraProvider>
    <WorkbenchLibraryDrawer isOpen onClose={jest.fn()} work={{
      threadId: 'thread', document: { project: null },
      hub: { workspace: { state: 'absent' }, library: { state: 'ready', items: [{
        file_id: 'owned-file', name: 'notes.md', availability: 'ready',
      }], next_cursor: 'page-2' } },
      copyFromLibrary: jest.fn(),
    }} />
  </ChakraProvider>);
  expect(await screen.findByRole('link', { name: 'Скачать notes.md' })).toBeVisible();
  getAccountWorkLibrary.mockRejectedValueOnce(new Error('unavailable'));
  fireEvent.click(screen.getByRole('button', { name: /Следующая/ }));
  expect(await screen.findByRole('button', { name: 'Повторить загрузку файлов' })).toBeVisible();
  expect(screen.getByRole('link', { name: 'Скачать notes.md' })).toBeVisible();
  const retry = screen.getByRole('button', { name: 'Повторить загрузку файлов' });
  retry.focus();
  expect(retry).toHaveFocus();
  fireEvent.click(retry);
  await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(3));
});

it('сохраняет скачивание без добавления файлов в несохранённый чат', async () => {
  render(<ChakraProvider><WorkbenchLibraryDrawer isOpen onClose={jest.fn()} work={{
    threadId: 'not-yet-saved', document: { project: null },
    hub: { workspace: { state: 'unselected' }, library: { state: 'ready', items: [{
      file_id: 'owned-file', name: 'notes.md', availability: 'ready',
    }] } },
  }} /></ChakraProvider>);
  expect(await screen.findByRole('link', { name: 'Скачать notes.md' })).toBeVisible();
  expect(screen.queryByRole('combobox', { name: 'Куда добавить файл' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Создать и добавить' })).toBeDisabled();
  expect(screen.getByTestId('work-upload-input')).toBeDisabled();
  expect(screen.getByText(/Для загрузки и добавления файлов выберите или создайте чат/)).toBeVisible();
});
