import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { LibraryPane } from '../../../src/features/workspace-room/components/LibraryPane';

jest.mock('@api/httpClient', () => ({ defaults: { baseURL: 'https://backend.example' } }));

const file = { file_id: 'owned file/id', name: 'Материалы.pdf', availability: 'ready' };
const show = (props = {}) => render(
  <ChakraProvider><LibraryPane items={[file]} onCopy={jest.fn()} {...props} /></ChakraProvider>,
);

it('keeps the pending copy button focused without admitting another copy', () => {
  const onCopy = jest.fn();
  const props = { items: [file], hasThread: true, workspaceReady: true, onCopy };
  const view = render(<ChakraProvider><LibraryPane {...props} /></ChakraProvider>);
  const copy = screen.getByRole('button');
  act(() => { copy.focus(); });
  view.rerender(<ChakraProvider><LibraryPane {...props} busy={`copy:${file.file_id}`} /></ChakraProvider>);
  expect(copy).toHaveFocus(); expect(copy).toHaveAttribute('aria-disabled', 'true');
  expect(copy).toHaveAttribute('aria-busy', 'true');
  fireEvent.click(copy); expect(onCopy).not.toHaveBeenCalled();
  view.rerender(<ChakraProvider><LibraryPane {...props} /></ChakraProvider>);
  expect(copy).toHaveFocus(); expect(copy).toHaveAttribute('aria-busy', 'false');
});

describe('Library download', () => {
  it('keeps compact account Library guidance and exceptional status without repeated origin badges', () => {
    const mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    show({ presentation: 'document', libraryOnlyUpload: true,
      items: [{ ...file, file_type: mime, availability: 'unavailable' }] });
    expect(screen.getByText('Загрузка только в Библиотеку. Добавление в проект — отдельно.')).toBeVisible();
    expect(screen.queryByText('библиотека', { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText(`${mime} · недоступен`)).toHaveStyle({ overflowWrap: 'anywhere' });
    expect(screen.getByText('Скачивание недоступно')).toBeVisible();
  });

  it('PDF materials disable copying a dirty document without disabling downloads or paging', () => {
    const onCopy = jest.fn();
    const onLoadMore = jest.fn();
    show({ presentation: 'document', copyDisabled: true, workspaceReady: true, hasThread: true,
      hasMore: true, onCopy, onLoadMore });
    const copy = screen.getByRole('button', { name: 'Добавить в рабочее место', exact: true });
    expect(copy).toBeDisabled();
    expect(copy).toHaveTextContent('Добавить');
    expect(screen.getByRole('link', { name: 'Скачать Материалы.pdf' })).toBeInTheDocument();
    fireEvent.click(copy);
    fireEvent.click(screen.getByRole('button', { name: 'Показать ещё', exact: true }));
    expect(onCopy).not.toHaveBeenCalled();
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it('keeps a delivered source-only outcome beside its Library item', () => {
    show({ outcomes: { [file.file_id]: 'library_saved' }, hasThread: true });
    expect(screen.getByTestId('work-library-outcome')).toHaveTextContent('Источник сохранён только в библиотеке');
    expect(screen.getByTestId('work-library-outcome')).toHaveStyle({ whiteSpace: 'normal', overflowWrap: 'anywhere' });
    expect(screen.getByRole('link', { name: 'Скачать Материалы.pdf' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Создать и добавить' })).toBeEnabled();
    const actions = screen.getByRole('link', { name: 'Скачать Материалы.pdf' }).closest('[data-toast-protected-actions]');
    expect(actions).not.toBeNull();
    expect(actions).toContainElement(screen.getByRole('button', { name: 'Создать и добавить' }));
  });

  it('distinguishes initial loading from an empty library', () => {
    show({ items: [], loading: true });
    expect(screen.getByRole('status')).toHaveTextContent('Загружаю библиотеку');
    expect(screen.queryByText(/пока нет доступных файлов/)).not.toBeInTheDocument();
  });

  it('keeps cached files downloadable during refresh', () => {
    show({ loading: true });
    expect(screen.getByRole('link', { name: 'Скачать Материалы.pdf' })).toBeInTheDocument();
    expect(screen.queryByText(/Загружаю библиотеку/)).not.toBeInTheDocument();
  });

  it('offers persistent inline page recovery without hiding files', () => {
    const onLoadMore = jest.fn();
    show({ hasMore: true, pageError: true, onLoadMore });
    expect(screen.getByRole('status')).toHaveTextContent('Уже загруженные файлы доступны');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку файлов' }));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('link', { name: 'Скачать Материалы.pdf' })).toBeInTheDocument();
  });

  it('downloads by owned ID without requiring a thread or workspace', () => {
    const onCopy = jest.fn();
    show({ hasThread: false, workspaceReady: false, onCopy });
    const link = screen.getByRole('link', { name: 'Скачать Материалы.pdf' });
    expect(link).toHaveAttribute('href', 'https://backend.example/api/service/files/v1/owned%20file%2Fid/download');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    fireEvent.click(link);
    expect(onCopy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Создать и добавить' })).toBeDisabled();
  });

  it('keeps downloads enabled during an unrelated mutation and stale snapshot', () => {
    show({ busy: 'copy:other', state: 'stale', hasThread: true });
    expect(screen.getByRole('link', { name: 'Скачать Материалы.pdf' })).toHaveAttribute('href');
    expect(screen.getByRole('button', { name: 'Создать и добавить' })).toBeDisabled();
  });

  it.each(['unavailable', 'unknown'])('does not offer a download for %s files', (availability) => {
    show({ items: [{ ...file, availability }], hasThread: true });
    expect(screen.queryByRole('link', { name: /Скачать/ })).not.toBeInTheDocument();
    expect(screen.getByText('Скачивание недоступно')).toBeInTheDocument();
  });

  it('never falls back to an injected storage URL or key without an owned ID', () => {
    show({ items: [{ file_id: '', name: 'legacy.pdf', file_url: 'https://private.example/secret', file_key: 'private-key' }] });
    expect(screen.queryByRole('link', { name: /Скачать/ })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain('private.example');
    expect(document.body.innerHTML).not.toContain('private-key');
  });
});
