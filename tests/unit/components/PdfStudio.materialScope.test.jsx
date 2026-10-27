import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfStudio } from '@features/workspace-room/components/PdfStudio';

jest.mock('@features/workspace-room/components/PdfStudioToolbar', () => ({
  PdfStudioToolbar: ({ onPanel }) => <button onClick={() => onPanel('Материалы')}>Материалы</button>,
}));
jest.mock('@features/workspace-room/components/PdfMaterialsPanel', () => ({
  PdfMaterialsPanel: ({ onOpenFile, error }) => <>
    <button onClick={() => onOpenFile('documents/a/main.tex')}>Основной файл</button>
    <button onClick={() => onOpenFile('documents/a/chapter.tex')}>Раздел</button>
    {error && <p role="alert">{error}</p>}
  </>,
}));
jest.mock('@features/workspace-room/components/PdfDocumentEditor', () => ({
  PdfDocumentEditor: ({ sourceRequest }) => <output data-testid="chosen-source">{sourceRequest?.path || ''}</output>,
}));
jest.mock('@features/workspace-room/components/DocumentChecksBar', () => ({ DocumentChecksBar: () => null }));

const makeWork = (path = 'documents/a', file = 'documents/a/main.tex') => ({
  threadId: 'material-scope', hub: { workspace: { state: 'ready', entries: [] } },
  file: { path: file }, document: { project: { path }, selectProject: jest.fn() },
});

it('оставляет минимум документа только при обычном вводе, не сжимая действия ассистента', () => {
  const ui = (expanded) => <ChakraProvider><PdfStudio work={makeWork()} active assistantExpanded={expanded} /></ChakraProvider>;
  const view = render(ui(false));
  const grid = screen.getByTestId('pdf-assistant-dock').parentElement;
  expect(grid).toHaveStyle({ gridTemplateRows: 'minmax(44px, 1fr) minmax(0, auto)' });
  view.rerender(ui(true));
  expect(grid).toHaveStyle({ gridTemplateRows: 'minmax(0, 1fr) auto' });
});

it('styles the PDF splitter without leaking touchAction into DOM attributes', () => {
  const matchMedia = window.matchMedia.getMockImplementation();
  window.matchMedia.mockImplementation(query => ({
    matches: query === '(min-width: 1100px)', media: query,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
  }));
  const errors = jest.spyOn(console, 'error').mockImplementation(() => {});
  try {
    render(<ChakraProvider><PdfStudio work={makeWork()} active /></ChakraProvider>);
    const splitter = screen.getByRole('separator', { name: 'Ширина редактора и превью' });
    expect(splitter).not.toHaveAttribute('touchaction');
    expect(errors.mock.calls.filter(args => args.some(arg => String(arg).includes('touchAction')))).toEqual([]);
    const before = Number(splitter.getAttribute('aria-valuenow'));
    fireEvent.keyDown(splitter, { key: 'ArrowRight' });
    expect(splitter).toHaveAttribute('aria-valuenow', String(before + 2));
  } finally {
    errors.mockRestore();
    window.matchMedia.mockImplementation(matchMedia);
  }
});

it('a late source completion cannot reopen a project after leaving and returning to it', () => {
  const onOpenFile = jest.fn();
  const ui = (work) => <ChakraProvider><PdfStudio work={work} active onOpenFile={onOpenFile} /></ChakraProvider>;
  const view = render(ui(makeWork()));
  fireEvent.click(screen.getByRole('button', { name: 'Материалы', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Основной файл', exact: true }));
  const pending = onOpenFile.mock.calls[0][1];
  view.rerender(ui(makeWork('documents/b', 'documents/b/main.tex')));
  view.rerender(ui(makeWork()));
  act(() => pending.onOpened());
  expect(screen.getByTestId('chosen-source')).toBeEmptyDOMElement();
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});

it('an earlier read failure cannot replace a newer successful source transition', () => {
  const onOpenFile = jest.fn();
  const ui = (work) => <ChakraProvider><PdfStudio work={work} active onOpenFile={onOpenFile} /></ChakraProvider>;
  const view = render(ui(makeWork()));
  fireEvent.click(screen.getByRole('button', { name: 'Материалы', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Основной файл', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Раздел', exact: true }));
  const first = onOpenFile.mock.calls[0][1];
  const second = onOpenFile.mock.calls[1][1];
  view.rerender(ui(makeWork('documents/a', 'documents/a/chapter.tex')));
  act(() => { second.onOpened(); first.onFailed(); });
  expect(screen.getByTestId('chosen-source')).toHaveTextContent('documents/a/chapter.tex');
  fireEvent.click(screen.getByRole('button', { name: 'Материалы', exact: true }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
