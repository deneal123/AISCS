import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import { WorkspaceTree } from '@features/workspace-room/components/WorkspaceTree';
import { PdfMaterialsPanel } from '@features/workspace-room/components/PdfMaterialsPanel';
import { buildWorkspaceTree } from '@features/workspace-room/model/workspaceTree';

const entries = [
  { path: 'documents/paper/main.tex', type: 'file', size: 1024 },
  { path: 'documents/paper/content/intro.tex', type: 'file', size: 100 },
  { path: 'documents/paper/artifacts/run/output.pdf', type: 'file', size: 2048 },
  { path: 'documents/paper/content', type: 'dir' },
  { path: 'documents/paper/assets/chart.png', type: 'file' },
  { path: 'documents/paper/empty', type: 'dir' },
];
const show = (props = {}) => render(<ChakraProvider theme={theme}><WorkspaceTree entries={entries}
  basePath="documents/paper" {...props} /></ChakraProvider>);

const transfer = () => ({ setData: jest.fn(), effectAllowed: '', dropEffect: '' });

it('moves files and directories into folders or the root using only its own drag source', () => {
  const onMove = jest.fn();
  show({ onMove });
  const file = screen.getByRole('button', { name: 'documents/paper/main.tex', exact: true });
  const folder = screen.getByRole('button', { name: 'documents/paper/content', exact: true });
  const root = screen.getByRole('region', { name: 'Файлы рабочего места' });
  const dataTransfer = transfer();
  fireEvent.dragStart(file, { dataTransfer });
  fireEvent.dragOver(folder, { dataTransfer });
  expect(dataTransfer.dropEffect).toBe('move');
  fireEvent.drop(folder, { dataTransfer });
  expect(onMove).toHaveBeenLastCalledWith({ path: 'documents/paper/main.tex', type: 'file' }, 'documents/paper/content/main.tex');
  fireEvent.dragStart(folder, { dataTransfer });
  fireEvent.drop(screen.getByRole('button', { name: 'documents/paper/empty', exact: true }), { dataTransfer });
  expect(onMove).toHaveBeenLastCalledWith({ path: 'documents/paper/content', type: 'dir' }, 'documents/paper/empty/content');
  fireEvent.click(folder);
  const nested = screen.getByRole('button', { name: 'documents/paper/content/intro.tex', exact: true });
  fireEvent.dragStart(nested, { dataTransfer });
  fireEvent.drop(root, { dataTransfer });
  expect(onMove).toHaveBeenLastCalledWith({ path: nested.getAttribute('aria-label'), type: 'file' }, 'documents/paper/intro.tex');
  fireEvent.drop(folder, { dataTransfer });
  expect(onMove).toHaveBeenCalledTimes(3);
});

it('rejects self/descendant drops and never enables dragging in passive or blocked trees', () => {
  const onMove = jest.fn();
  const view = show({ onMove });
  const folder = screen.getByRole('button', { name: 'documents/paper/content', exact: true });
  const dataTransfer = transfer();
  fireEvent.dragStart(folder, { dataTransfer });
  fireEvent.drop(folder, { dataTransfer });
  expect(onMove).not.toHaveBeenCalled();
  view.rerender(<ChakraProvider theme={theme}><WorkspaceTree entries={entries} basePath="documents/paper" onMove={onMove} moveDisabled /></ChakraProvider>);
  expect(folder).toHaveAttribute('draggable', 'false');
  fireEvent.dragStart(folder, { dataTransfer });
  fireEvent.drop(screen.getByRole('button', { name: 'documents/paper/empty', exact: true }), { dataTransfer });
  expect(onMove).not.toHaveBeenCalled();
});

it('never labels an incomplete directory as empty', () => {
  show({ entries: [{ path: 'documents/paper/deep', type: 'dir', incomplete: true }] });
  fireEvent.click(screen.getByRole('button', { name: 'documents/paper/deep', exact: true }));
  expect(screen.getByText('Содержимое загружено не полностью')).toBeVisible();
  expect(screen.queryByText('Папка пуста')).not.toBeInTheDocument();
});

it('shows relative names, synthesizes missing parents and sorts directories before files', () => {
  const nodes = buildWorkspaceTree(entries, 'documents/paper');
  expect(nodes.map((item) => item.name)).toEqual(['artifacts', 'assets', 'content', 'empty', 'main.tex']);
  expect(nodes[2].children.map((item) => item.name)).toEqual(['intro.tex']);
  expect(buildWorkspaceTree([...entries, { path: 'documents/paper2/foreign.tex', type: 'file' }], 'documents/paper')).toEqual(nodes);
  show();
  expect(screen.getByRole('button', { name: 'documents/paper/main.tex', exact: true })).toHaveTextContent('main.tex');
  expect(screen.queryByText('documents/paper/main.tex')).not.toBeInTheDocument();
  expect(screen.queryByText('output.pdf')).not.toBeInTheDocument();
});

it('opens folders with native keyboard activation without selecting files or starting work', async () => {
  const onSelect = jest.fn(); show({ onSelect, disabled: true });
  const folder = screen.getByRole('button', { name: 'documents/paper/content', exact: true });
  act(() => { folder.focus(); userEvent.keyboard('{Enter}'); });
  expect(folder).toHaveAttribute('aria-expanded', 'true');
  expect(folder).toHaveFocus();
  expect(document.getElementById(folder.getAttribute('aria-controls'))).toBeVisible();
  const file = screen.getByRole('button', { name: 'documents/paper/content/intro.tex', exact: true });
  expect(file).toBeDisabled(); fireEvent.click(file); expect(onSelect).not.toHaveBeenCalled();
  act(() => { userEvent.keyboard(' '); }); expect(folder).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'documents/paper/empty', exact: true }));
  expect(screen.getByText('Папка пуста')).toBeVisible();
});

it('reveals selected ancestors, preserves collapsed folders on refresh and selects exact paths', () => {
  const onSelect = jest.fn();
  const props = { entries, basePath: 'documents/paper', selected: 'documents/paper/content/intro.tex', onSelect };
  const view = show(props);
  const folder = screen.getByRole('button', { name: 'documents/paper/content', exact: true });
  fireEvent.click(screen.getByRole('button', { name: props.selected, exact: true }));
  expect(onSelect).toHaveBeenCalledWith(props.selected);
  expect(screen.getByTestId('workspace-inspected-path')).toHaveTextContent(props.selected);
  fireEvent.click(folder);
  view.rerender(<ChakraProvider theme={theme}><WorkspaceTree {...props} entries={[...entries]} /></ChakraProvider>);
  expect(folder).toHaveAttribute('aria-expanded', 'false');
});

it('keeps binary materials non-editable and hides other projects and the empty documents shell', () => {
  const work = { document: { project: { path: 'documents/paper' } },
    hub: { workspace: { state: 'ready', entries: [...entries, { path: 'documents', type: 'dir' },
      { path: 'documents/other/main.tex', type: 'file' }, { path: 'notes.txt', type: 'file' }] } }, file: {}, load: jest.fn() };
  render(<ChakraProvider theme={theme}><PdfMaterialsPanel work={work} /></ChakraProvider>);
  expect(screen.queryByRole('button', { name: 'documents', exact: true })).not.toBeInTheDocument();
  expect(screen.queryByText('other')).not.toBeInTheDocument();
  const sharedFiles = screen.getByRole('button', { name: /Общие файлы чата/ });
  expect(sharedFiles).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(sharedFiles);
  expect(screen.getByRole('button', { name: 'notes.txt', exact: true })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'documents/paper/assets', exact: true }));
  expect(screen.getByRole('button', { name: 'documents/paper/assets/chart.png', exact: true })).toBeDisabled();
});

it('does not carry a path readout or expanded folders into a different PDF project', () => {
  const makeWork = (path) => ({ document: { project: { path } }, hub: { workspace: { state: 'ready', entries: [
    { path: 'documents/first/content/notes.txt', type: 'file' },
    { path: 'documents/second/content/notes.txt', type: 'file' },
  ] } }, file: {} });
  const view = render(<ChakraProvider theme={theme}><PdfMaterialsPanel work={makeWork('documents/first')} /></ChakraProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'documents/first/content', exact: true }));
  fireEvent.focus(screen.getByRole('button', { name: 'documents/first/content/notes.txt', exact: true }));
  expect(screen.getByTestId('workspace-inspected-path')).toHaveTextContent('documents/first/content/notes.txt');
  view.rerender(<ChakraProvider theme={theme}><PdfMaterialsPanel work={makeWork('documents/second')} /></ChakraProvider>);
  expect(screen.queryByTestId('workspace-inspected-path')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'documents/second/content', exact: true })).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByText('notes.txt')).not.toBeInTheDocument();
});
