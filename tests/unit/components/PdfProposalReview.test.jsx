import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfProposalReview } from '@features/workspace-room/components/PdfProposalReview';
import { getDocumentProposal, acquireWorkspaceLease, releaseWorkspaceLease, saveDocumentDraft } from '@api/chat';

jest.mock('@api/chat', () => ({ getDocumentProposal: jest.fn(), acquireWorkspaceLease: jest.fn(),
  releaseWorkspaceLease: jest.fn(), saveDocumentDraft: jest.fn() }));

const proposal = () => ({
  proposal_id: 'proposal-1', path: 'documents/paper', expected_revision: 'r1',
  authoring_version: 1, draft_digest: 'a'.repeat(64), stale: false,
  before: { title: 'Обзор', blocks: [
    { block_id: 'intro', kind: 'section', title: 'Введение', level: 1 },
    { block_id: 'results', kind: 'table', title: 'Результаты', columns: ['Метод', 'Значение'], rows: [['A', '2']] },
    { block_id: 'source', kind: 'citation', text: 'Данные', source_id: 1 },
  ] },
  draft: { title: 'Обзор', blocks: [
    { block_id: 'intro', kind: 'section', title: 'Введение', level: 2 },
    { block_id: 'results', kind: 'table', title: 'Результаты', columns: ['Метод', 'Значение'], rows: [['A', '3']] },
    { block_id: 'source', kind: 'citation', text: 'Данные', source_id: 2 },
  ] },
});
const deferred = () => {
  let resolve;
  const promise = new Promise((accept) => { resolve = accept; });
  return { promise, resolve };
};
const makeProps = () => ({ threadId: 'thread-1', proposalId: 'proposal-1', active: true, dirty: false,
  project: { path: 'documents/paper' }, work: { load: jest.fn().mockResolvedValue({}),
    document: { loadProject: jest.fn().mockResolvedValue({}), loadAuthoring: jest.fn().mockResolvedValue({}) } } });
const ui = (props) => <ChakraProvider><PdfProposalReview {...props} /></ChakraProvider>;
const open = async (expected = /Изменено фрагментов: 3/) => {
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть изменения', exact: true }));
  await screen.findByText(expected);
};
beforeEach(() => {
  jest.clearAllMocks(); getDocumentProposal.mockResolvedValue(proposal());
  acquireWorkspaceLease.mockResolvedValue({ fence: 9 }); releaseWorkspaceLease.mockResolvedValue({});
  saveDocumentDraft.mockResolvedValue({ revision: 'r2' });
});

it('shows heading level, table cells and citations before applying; Close receives initial focus', async () => {
  render(ui(makeProps())); await open();
  expect(screen.getByRole('button', { name: 'Закрыть', exact: true })).toHaveFocus();
  const section = screen.getByRole('region', { name: 'Изменение 1' });
  expect(section).toHaveTextContent('Заголовок · уровень 1');
  expect(section).toHaveTextContent('Заголовок · уровень 2');
  expect(screen.getByRole('region', { name: 'Изменение 2' })).toHaveTextContent('A | 2');
  expect(screen.getByRole('region', { name: 'Изменение 2' })).toHaveTextContent('A | 3');
  expect(screen.getByRole('region', { name: 'Изменение 3' })).toHaveTextContent('Источник: 2');
  expect(saveDocumentDraft).not.toHaveBeenCalled();
});

it('closes a pending read, aborts observation and ignores its late result', async () => {
  const pending = deferred(); getDocumentProposal.mockReturnValueOnce(pending.promise);
  render(ui(makeProps()));
  const trigger = screen.getByRole('button', { name: 'Посмотреть изменения', exact: true });
  fireEvent.click(trigger);
  expect(screen.getByRole('status')).toHaveTextContent('Загружаю правки');
  const signal = getDocumentProposal.mock.calls[0][2].signal;
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть', exact: true }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve(proposal()));
  expect(screen.queryByText(/Изменено фрагментов:/)).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it.each([null, { ...proposal(), before: null }, { ...proposal(), draft_digest: null },
  { ...proposal(), path: 'documents/another' }, { ...proposal(), proposal_id: 'other' }])(
  'fails closed on malformed or foreign proposal %p without dispatching a write', async (value) => {
    getDocumentProposal.mockResolvedValueOnce(value); render(ui(makeProps()));
    fireEvent.click(screen.getByRole('button', { name: 'Посмотреть изменения' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить правки');
    expect(screen.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
    expect(acquireWorkspaceLease).not.toHaveBeenCalled();
  },
);

it.each(['stale', 'dirty'])('blocks %s apply without a lease or write', async (reason) => {
  const props = makeProps();
  if (reason === 'stale') getDocumentProposal.mockResolvedValueOnce({ ...proposal(), stale: true });
  else props.dirty = true;
  render(ui(props)); await open(reason === 'stale' ? /Базовая версия изменилась/ : undefined);
  expect(screen.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
  expect(acquireWorkspaceLease).not.toHaveBeenCalled();
});

it('rejects explicitly without a write and restores focus to its outcome', async () => {
  render(ui(makeProps())); await open();
  fireEvent.click(screen.getByRole('button', { name: 'Отклонить', exact: true }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent('Правки отклонены');
  expect(screen.getByRole('status')).toHaveFocus();
  expect(saveDocumentDraft).not.toHaveBeenCalled();
});

it('applies once with pinned version/digest and never recompiles', async () => {
  const props = makeProps(); render(ui(props)); await open();
  const button = screen.getByRole('button', { name: 'Применить', exact: true });
  fireEvent.click(button); fireEvent.click(button);
  await waitFor(() => expect(saveDocumentDraft).toHaveBeenCalledTimes(1));
  expect(saveDocumentDraft.mock.calls[0][1]).toMatchObject({ path: 'documents/paper', expected_revision: 'r1',
    authoring_version: 1, draft_digest: 'a'.repeat(64), fence: 9 });
  await waitFor(() => expect(releaseWorkspaceLease).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent('Правки применены. Пересоберите PDF');
});

it('reviews structural additions, deletions and positions before one version-checked save', async () => {
  const value = proposal();
  value.patch_version = 2;
  value.draft.blocks = [value.before.blocks[1], value.before.blocks[0],
    { block_id: 'new_notes', kind: 'paragraph', text: 'Новый фрагмент' }];
  getDocumentProposal.mockResolvedValueOnce(value);
  render(ui(makeProps()));
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть изменения', exact: true }));
  await screen.findByText(/Изменено фрагментов: 4/);
  expect(screen.getByText('Блока не было')).toBeInTheDocument();
  expect(screen.getByText('Блок будет удалён')).toBeInTheDocument();
  expect(screen.getByText('Перемещение · позиция 2 → 1')).toBeInTheDocument();
  expect(screen.getByText('Перемещение · позиция 1 → 2')).toBeInTheDocument();
  expect(saveDocumentDraft).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Применить', exact: true }));
  await waitFor(() => expect(saveDocumentDraft).toHaveBeenCalledTimes(1));
  expect(saveDocumentDraft.mock.calls[0][1].draft).toEqual(value.draft);
  expect(saveDocumentDraft.mock.calls[0][1]).toMatchObject({ expected_revision: 'r1', fence: 9 });
});

it('refreshes an acknowledged write without repeating it when editor refresh fails', async () => {
  const props = makeProps(); props.work.document.loadProject.mockRejectedValueOnce(new Error('private failure'));
  render(ui(props)); await open(); fireEvent.click(screen.getByRole('button', { name: 'Применить', exact: true }));
  await screen.findByText('Правки сохранены, но обновить редактор не удалось.');
  await waitFor(() => expect(releaseWorkspaceLease).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'Обновить документ', exact: true }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Правки применены. Пересоберите PDF'));
  expect(saveDocumentDraft).toHaveBeenCalledTimes(1);
  expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('private failure')).not.toBeInTheDocument();
});

it('requires refreshed review after a revision conflict, not an automatic write retry', async () => {
  saveDocumentDraft.mockRejectedValueOnce({ status: 409 }); render(ui(makeProps())); await open();
  fireEvent.click(screen.getByRole('button', { name: 'Применить', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Документ изменился');
  expect(screen.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
  expect(saveDocumentDraft).toHaveBeenCalledTimes(1);
});

it('does not write when local editing starts while lease acquisition is pending', async () => {
  const pending = deferred(); acquireWorkspaceLease.mockReturnValueOnce(pending.promise);
  const props = makeProps(); const view = render(ui(props)); await open();
  fireEvent.click(screen.getByRole('button', { name: 'Применить', exact: true }));
  await waitFor(() => expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1));
  view.rerender(ui({ ...props, dirty: true }));
  await act(async () => pending.resolve({ fence: 9 }));
  await waitFor(() => expect(releaseWorkspaceLease).toHaveBeenCalledTimes(1));
  expect(saveDocumentDraft).not.toHaveBeenCalled();
});

it('ignores the previous project read after switching projects', async () => {
  const pending = deferred(); getDocumentProposal.mockReturnValueOnce(pending.promise);
  const props = makeProps(); const view = render(ui(props));
  fireEvent.click(screen.getByRole('button', { name: 'Посмотреть изменения' }));
  view.rerender(ui({ ...props, proposalId: 'proposal-2', project: { path: 'documents/other' } }));
  await act(async () => pending.resolve(proposal()));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.queryByText('Введение')).not.toBeInTheDocument();
  expect(within(screen.getByRole('button', { name: 'Посмотреть изменения' })).queryByText('Применить')).toBeNull();
});

it('releases a retired lease without applying its proposal to another project', async () => {
  const pending = deferred(); acquireWorkspaceLease.mockReturnValueOnce(pending.promise);
  const props = makeProps(); const view = render(ui(props)); await open();
  fireEvent.click(screen.getByRole('button', { name: 'Применить', exact: true }));
  await waitFor(() => expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1));
  view.rerender(ui({ ...props, proposalId: 'proposal-2', project: { path: 'documents/other' } }));
  await act(async () => pending.resolve({ fence: 9 }));
  await waitFor(() => expect(releaseWorkspaceLease).toHaveBeenCalledTimes(1));
  expect(releaseWorkspaceLease.mock.calls[0].slice(0, 3)).toEqual(['thread-1', 'documents/paper', 9]);
  expect(saveDocumentDraft).not.toHaveBeenCalled();
  expect(props.work.document.loadProject).not.toHaveBeenCalled();
});

it('requires a fresh read after an ambiguous write failure and never retries the mutation itself', async () => {
  saveDocumentDraft.mockRejectedValueOnce({ status: 503, detail: 'private provider exception' });
  render(ui(makeProps())); await open();
  fireEvent.click(screen.getByRole('button', { name: 'Применить', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить применение');
  expect(screen.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
  getDocumentProposal.mockResolvedValueOnce({ ...proposal(), stale: true });
  fireEvent.click(screen.getByRole('button', { name: 'Обновить просмотр', exact: true }));
  await screen.findByText('Предложение устарело. Применение заблокировано.');
  expect(saveDocumentDraft).toHaveBeenCalledTimes(1);
  expect(acquireWorkspaceLease).toHaveBeenCalledTimes(1);
});

it('does not publish a proposal with no actual changes', async () => {
  const same = proposal(); same.draft = same.before; getDocumentProposal.mockResolvedValueOnce(same);
  render(ui(makeProps())); fireEvent.click(screen.getByRole('button', { name: 'Посмотреть изменения' }));
  await screen.findByText('В предложении нет отличий от текущего документа.');
  expect(screen.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
  expect(acquireWorkspaceLease).not.toHaveBeenCalled();
});
