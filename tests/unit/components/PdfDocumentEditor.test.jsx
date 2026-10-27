import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfDocumentEditor } from '@features/workspace-room/components/PdfDocumentEditor';
import { PdfBlockFields } from '@features/workspace-room/components/PdfBlockFields';
import { acquireWorkspaceLease, saveDocumentDraft, getDocumentSources } from '@api/chat';

jest.mock('@api/chat', () => ({ acquireWorkspaceLease: jest.fn(), releaseWorkspaceLease: jest.fn().mockResolvedValue({}), saveDocumentDraft: jest.fn(), getDocumentSources: jest.fn() }));
const draft = { version: 1, title: 'Обзор', blocks: [
  { block_id: 'heading', kind: 'section', title: 'Введение', text: '', level: 1 },
  { block_id: 'intro', kind: 'paragraph', text: 'Исходный текст' },
] };
const work = {
  hub: { workspace: { state: 'ready', entries: [] }, library: { items: [] } },
  threadId: 't1', dirty: false, document: {
    project: { path: 'documents/paper', revision: 'r1', authoring_version: 1, draft_digest: 'a'.repeat(64) },
    authoring: { state: 'ready', value: { draft, authoring_version: 1, draft_digest: 'a'.repeat(64) } },
    loadProject: jest.fn().mockResolvedValue({}), loadAuthoring: jest.fn().mockResolvedValue({}),
  }, load: jest.fn().mockResolvedValue({}),
};
const props = { work, active: true, selectedBlocks: [], onSelectBlocks: jest.fn(), onDirtyChange: jest.fn() };
const ui = (next = props) => <ChakraProvider><PdfDocumentEditor {...next} /></ChakraProvider>;

beforeEach(() => {
  jest.clearAllMocks();
  HTMLElement.prototype.scrollIntoView = jest.fn();
  acquireWorkspaceLease.mockResolvedValue({ fence: 3 });
  saveDocumentDraft.mockResolvedValue({ revision: 'r3', authoring_version: 2, draft_digest: 'c'.repeat(64) });
  getDocumentSources.mockResolvedValue({ revision: 'r1', sources: [{ source_id: 2, title: 'Проверяемое исследование', year: '2024' }], unresolved_count: 0 });
});

it('adds a citation from the actual bibliography only after source selection and explicit Save', async () => {
  render(ui());
  const kind = screen.getByRole('combobox', { name: 'Тип нового блока' });
  fireEvent.change(kind, { target: { value: 'Цитирование' } });
  fireEvent.keyDown(kind, { key: 'ArrowDown' }); fireEvent.keyDown(kind, { key: 'Enter' });
  await waitFor(() => expect(getDocumentSources).toHaveBeenCalledTimes(1));
  const add = screen.getByRole('button', { name: 'Добавить блок' });
  expect(add).toBeDisabled();
  const select = screen.getByRole('combobox', { name: 'Источник цитаты' });
  await waitFor(() => expect(select).not.toBeDisabled());
  fireEvent.keyDown(select, { key: 'ArrowDown' });
  fireEvent.click(screen.getByRole('option', { name: 'Проверяемое исследование · 2024' }));
  fireEvent.click(add);
  expect(saveDocumentDraft).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox', { name: 'Текст блока new_1' }), { target: { value: 'Текст с цитатой' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить', exact: true }));
  await waitFor(() => expect(saveDocumentDraft).toHaveBeenCalledTimes(1));
  expect(saveDocumentDraft.mock.calls[0][1].draft.blocks.at(-1)).toMatchObject({ kind: 'citation', source_id: 2, text: 'Текст с цитатой' });
});

it('renders a real heading without an empty body field, and exposes the save action', () => {
  render(ui());
  expect(screen.getByRole('textbox', { name: 'Заголовок блока heading' })).toHaveValue('Введение');
  expect(screen.queryByRole('textbox', { name: 'Текст блока heading' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Структура', exact: true })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Сохранено', exact: true })).toBeDisabled();
});

it('retains an offline semantic draft and never writes with a late lease after verification fails', async () => {
  let releaseLease;
  acquireWorkspaceLease.mockReturnValueOnce(new Promise(resolve => { releaseLease = resolve; }));
  const view = render(ui());
  const title = screen.getByRole('textbox', { name: 'Название документа', exact: true });
  fireEvent.change(title, { target: { value: 'Несохранённый локальный текст' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить', exact: true }));
  await waitFor(() => expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1));
  view.rerender(ui({ ...props, work: { ...work, hub: { ...work.hub, workspace: { ...work.hub.workspace, state: 'unavailable' } } } }));
  await act(async () => releaseLease({ fence: 3 }));
  expect(title).toHaveValue('Несохранённый локальный текст');
  expect(screen.getByTestId('pdf-draft-recovery')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Скачать черновик JSON' })).toBeEnabled();
  fireEvent.keyDown(title, { key: 's', ctrlKey: true });
  expect(saveDocumentDraft).not.toHaveBeenCalled();
  expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1);
});

it('uses one save control for clean, dirty, pending and acknowledged states', async () => {
  let resolve;
  saveDocumentDraft.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const view = render(ui());
  expect(screen.getByRole('button', { name: 'Сохранено', exact: true })).toBeDisabled();
  expect(view.container.querySelector('[data-pdf-editor-status]')).toBeNull();
  fireEvent.change(screen.getByRole('textbox', { name: 'Текст блока intro' }), { target: { value: 'Правка' } });
  const save = screen.getByRole('button', { name: 'Сохранить', exact: true });
  expect(save).toBeEnabled();
  fireEvent.click(save);
  expect(await screen.findByRole('button', { name: 'Сохраняю…', exact: true })).toHaveAttribute('aria-busy', 'true');
  await waitFor(() => expect(resolve).toBeDefined());
  await act(async () => resolve({ revision: 'r3', authoring_version: 2, draft_digest: 'c'.repeat(64) }));
  expect(screen.getByRole('button', { name: 'Сохранено', exact: true })).toBeDisabled();
  expect(saveDocumentDraft).toHaveBeenCalledTimes(1);
});

it('focuses a newly added block instead of leaving it below the editor viewport', () => {
  render(ui());
  fireEvent.click(screen.getByRole('button', { name: 'Добавить блок', exact: true }));
  expect(screen.getByRole('textbox', { name: 'Текст блока new_1', exact: true })).toHaveFocus();
  expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'instant' });
  expect(screen.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toHaveValue('Исходный текст');
  expect(saveDocumentDraft).not.toHaveBeenCalled();
});

it('requires explicit replacement consent before creating semantic content over a source-only project', async () => {
  const sourceOnly = { ...work, document: { ...work.document,
    project: { ...work.document.project, authoring_version: 0, draft_digest: null },
    authoring: { state: 'absent', value: null },
  } };
  render(ui({ ...props, work: sourceOnly }));
  fireEvent.click(screen.getByRole('button', { name: 'Новое содержание без ИИ' }));
  expect(screen.getByRole('alertdialog')).toHaveTextContent('Текущие исходники LaTeX будут заменены');
  expect(acquireWorkspaceLease).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Отмена', exact: true }));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  expect(saveDocumentDraft).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Новое содержание без ИИ' }));
  fireEvent.click(screen.getByRole('button', { name: 'Создать новое содержание', exact: true }));
  await waitFor(() => expect(saveDocumentDraft).toHaveBeenCalledTimes(1));
  expect(saveDocumentDraft.mock.calls[0][1]).toMatchObject({ authoring_version: 0, expected_revision: 'r1', draft_digest: null });
});

it('pins the edit base when background project facts change instead of adopting an unseen revision', async () => {
  const view = render(ui());
  fireEvent.change(screen.getByRole('textbox', { name: 'Текст блока intro' }), { target: { value: 'Моя правка' } });
  view.rerender(ui({ ...props, work: { ...work, document: { ...work.document,
    project: { ...work.document.project, revision: 'r2', authoring_version: 2, draft_digest: 'b'.repeat(64) },
  } } }));
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить', exact: true }));
  await waitFor(() => expect(saveDocumentDraft).toHaveBeenCalledTimes(1));
  expect(saveDocumentDraft.mock.calls[0][1]).toMatchObject({ expected_revision: 'r1', authoring_version: 1, draft_digest: 'a'.repeat(64) });
  expect(saveDocumentDraft.mock.calls[0][1].draft.blocks[1].text).toBe('Моя правка');
});

it('supports explicit Ctrl+S without turning save into a compilation', async () => {
  render(ui());
  const input = screen.getByRole('textbox', { name: 'Текст блока intro' });
  fireEvent.change(input, { target: { value: 'Правка' } });
  fireEvent.keyDown(input, { key: 's', ctrlKey: true });
  await waitFor(() => expect(saveDocumentDraft).toHaveBeenCalledTimes(1));
});

it('edits signature party items used by the renderer, never an ignored text field', () => {
  const onChange = jest.fn();
  render(<ChakraProvider><PdfBlockFields block={{ block_id: 'parties', kind: 'signature', items: ['Заказчик', 'Исполнитель'] }} onChange={onChange} /></ChakraProvider>);
  fireEvent.change(screen.getByRole('textbox', { name: 'Сторона подписи 1' }), { target: { value: 'ООО Заказчик' } });
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ items: ['ООО Заказчик', 'Исполнитель'] }));
  expect(screen.queryByRole('textbox', { name: 'Текст блока parties' })).not.toBeInTheDocument();
});

it('can reveal an empty section body and adopts non-empty body text from a refreshed draft', () => {
  const view = render(<ChakraProvider><PdfBlockFields block={draft.blocks[0]} onChange={jest.fn()} /></ChakraProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Добавить текст раздела' }));
  expect(screen.getByRole('textbox', { name: 'Текст блока heading' })).toBeInTheDocument();
  view.rerender(<ChakraProvider><PdfBlockFields block={{ ...draft.blocks[0], text: 'Новая аннотация' }} onChange={jest.fn()} /></ChakraProvider>);
  expect(screen.getByRole('textbox', { name: 'Текст блока heading' })).toHaveValue('Новая аннотация');
});

it('adds a table column without shifting existing cells', () => {
  const onChange = jest.fn();
  render(<ChakraProvider><PdfBlockFields block={{ block_id: 'table', kind: 'table', columns: ['Метод'], rows: [['A']] }} onChange={onChange} /></ChakraProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Добавить столбец' }));
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ columns: ['Метод', 'Столбец 2'], rows: [['A', '']] }));
});

it.each(['figure', 'slide'])('selects a project-owned image for %s without saving or generating', (kind) => {
  const onChange = jest.fn();
  render(<ChakraProvider><PdfBlockFields block={{ block_id: 'image', kind, asset_path: '', title: 'Подпись' }}
    images={[{ value: 'figures/chart.png', label: 'chart.png' }]} onChange={onChange} /></ChakraProvider>);
  const selector = screen.getByRole('combobox', { name: 'Изображение блока image' });
  fireEvent.keyDown(selector, { key: 'ArrowDown' }); fireEvent.keyDown(selector, { key: 'Enter' });
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ asset_path: 'figures/chart.png', title: 'Подпись' }));
  expect(saveDocumentDraft).not.toHaveBeenCalled();
});

it('retains a missing image reference on refresh instead of silently clearing it', () => {
  const onChange = jest.fn();
  const view = render(<ChakraProvider><PdfBlockFields block={{ block_id: 'image', kind: 'figure', asset_path: 'figures/old.png' }}
    images={[]} onChange={onChange} /></ChakraProvider>);
  expect(screen.getByRole('status')).toHaveTextContent('Ссылка сохранена');
  expect(screen.getByText('figures/old.png · нет в списке')).toBeVisible();
  view.rerender(<ChakraProvider><PdfBlockFields block={{ block_id: 'image', kind: 'figure', asset_path: 'figures/old.png' }}
    images={[{ value: 'figures/old.png', label: 'old.png' }]} onChange={onChange} /></ChakraProvider>);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
});
