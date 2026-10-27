import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import IdeStudio from '@features/workspace-room/components/IdeStudio';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ listIdeRepositories: jest.fn(), getIdeRuntime: jest.fn(), readIdeTree: jest.fn(), readIdeFile: jest.fn(), registerIdeRepository: jest.fn(), provisionIdeRuntime: jest.fn(), prepareIdeWorkspace: jest.fn(), operateIdeGit: jest.fn(), cloneIdeRepository: jest.fn(), getIdeClone: jest.fn(), getIdeCloneRecovery: jest.fn(), leaseIdeFile: jest.fn(), writeIdeFile: jest.fn(), getIdeAgentCommands: jest.fn(), getIdeCheckpointCapabilities: jest.fn(), listIdeCheckpoints: jest.fn() }));
// This suite covers editor/repository ownership. The real console UI is exercised
// in ide-studio.spec.js; keep its extra control tree out of timing-sensitive reads.
jest.mock('@features/workspace-room/components/IdeConsole', () => () => <section aria-label="Консоль разработчика" />);
// Multi-stage Chakra editor flows take ~3.7 s even in isolation on Windows.
// Give the full component suite headroom without weakening any assertions.
jest.setTimeout(10000);
const repo = '00000000-0000-0000-0000-000000000001';
const generation = 'a'.repeat(64);

it('hands a denied thread to the shared navigation owner without creating a repository', async () => {
  api.listIdeRepositories.mockRejectedValueOnce({ response: { status: 404 } });
  const onThreadUnavailable = jest.fn();
  render(<ChakraProvider theme={theme}><IdeStudio threadId="other-account-thread" onThreadUnavailable={onThreadUnavailable} /></ChakraProvider>);
  await waitFor(() => expect(onThreadUnavailable).toHaveBeenCalledWith('other-account-thread'));
  expect(api.prepareIdeWorkspace).not.toHaveBeenCalled();
});
const show = () => render(<ChakraProvider theme={theme}><IdeStudio threadId="thread" /></ChakraProvider>);
const ready = (id = repo) => ({ repository_id: id, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } });
const prepared = (id = repo) => ({ repository: { repository_id: id, name: 'Repo', state: 'registered' }, runtime: ready(id), git: { initialized: true, branch: 'main' } });
beforeEach(() => {
  jest.resetAllMocks();
  api.getIdeCheckpointCapabilities.mockResolvedValue({ enabled: false });
  api.getIdeAgentCommands.mockImplementation(async (_thread, id, generation) => ({ repository_id: id, generation, entries: [] }));
  api.getIdeCloneRecovery.mockResolvedValue({ attempt: null });
  api.prepareIdeWorkspace.mockImplementation((thread, id) => Promise.resolve(prepared(id || repo)));
  api.getIdeRuntime.mockImplementation((thread, id) => Promise.resolve(ready(id)));
  api.readIdeTree.mockImplementation((thread, id) => Promise.resolve({ repository_id: id, generation, entries: [], truncated: false }));
  api.operateIdeGit.mockImplementation((thread, id) => Promise.resolve({ repository_id: id, generation, initialized: true, branch: 'main' }));
  api.leaseIdeFile.mockImplementation(async (_thread, id, value) => ({ repository_id: id, generation: value.generation, path: value.path, fence: 3, expires_at: Math.floor(Date.now() / 1000) + 120 }));
  window.matchMedia.mockImplementation(query => ({ matches: true, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
});

it('возвращает фокус на кнопку истории после открытия без предварительного фокуса', async () => {
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Repo', state: 'registered' }], next_offset: null });
  api.getIdeCheckpointCapabilities.mockResolvedValue({ enabled: true });
  api.listIdeCheckpoints.mockResolvedValue({ repository_id: repo, items: [], truncated: false,
    usage: { used_bytes: 0, max_bytes: 100000, max_snapshot_bytes: 10000 },
    runtime: { generation, state: 'ready' }, last_restore: null });
  await act(async () => show());
  const opener = await screen.findByRole('button', { name: 'История проекта', exact: true });
  // fireEvent.click не фокусирует кнопку, как и pointer-click в мобильном WebKit.
  await act(async () => fireEvent.click(opener));
  const dialog = await screen.findByRole('dialog', { name: /История проекта/ });
  await act(async () => fireEvent.keyDown(dialog, { key: 'Escape', code: 'Escape' }));
  await waitFor(() => expect(opener).toHaveFocus());
});

it('keeps runtime details out of the work area and opens passive accessible status help', async () => {
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Repo', state: 'registered' }], next_offset: null });
  show();
  const status = await screen.findByRole('button', { name: 'Состояние среды: Среда доступна', exact: true });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Обновить IDE' })).toBeEnabled());
  const preparations = api.prepareIdeWorkspace.mock.calls.length;
  const reads = api.getIdeRuntime.mock.calls.length;
  expect(screen.queryByText('Отдельная временная среда')).not.toBeInTheDocument();
  expect(screen.queryByText(/Запись в среду не является/)).not.toBeInTheDocument();
  fireEvent.click(status);
  await waitFor(() => expect(screen.getByText(/Запись в среду не является/)).toBeVisible());
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(preparations);
  expect(api.getIdeRuntime).toHaveBeenCalledTimes(reads);
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть сведения о среде' }));
  await waitFor(() => expect(status).toHaveFocus());
});

async function openDraft(content = 'my unsaved draft') {
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Repo', state: 'registered' }], next_offset: null });
  api.readIdeTree.mockImplementation(async () => ({ repository_id: repo, generation, entries: [{ path: 'main.py', type: 'file', size: 3, incomplete: false }], truncated: false }));
  api.readIdeFile.mockResolvedValue({ repository_id: repo, generation, path: 'main.py', kind: 'text', content: 'old', size: 3, digest: 'b'.repeat(64), truncated: false });
  const navigation = jest.fn(action => action());
  const writeText = jest.fn().mockResolvedValue();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  await act(async () => render(<ChakraProvider theme={theme}><IdeStudio threadId="thread" onRequestNavigation={navigation} /></ChakraProvider>));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Обновить IDE', exact: true })).toBeEnabled());
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'main.py', exact: true })));
  const edit = await screen.findByRole('button', { name: 'Редактировать', exact: true });
  await waitFor(() => expect(edit).toBeEnabled());
  await act(async () => fireEvent.click(edit));
  const input = await screen.findByRole('textbox', { name: 'Содержимое main.py', exact: true });
  fireEvent.change(input, { target: { value: content } });
  navigation.mockClear(); navigation.mockImplementation(() => {});
  return { input, navigation, writeText };
}

it.each(['expired', 'unknown', 'unavailable'])('checks %s runtime without discarding a draft or preparing another environment', async state => {
  const { input, navigation, writeText } = await openDraft();
  const preparations = api.prepareIdeWorkspace.mock.calls.length;
  const registryReads = api.listIdeRepositories.mock.calls.length;
  api.getIdeRuntime.mockResolvedValue({ repository_id: repo, workspace: { state, expires_at: 1, can_retry: false } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Обновить IDE', exact: true })));
  expect(navigation).not.toHaveBeenCalled();
  expect(input).toHaveValue('my unsaved draft');
  expect(input).toHaveAttribute('readonly');
  expect(screen.getByRole('button', { name: 'Записать в среду', exact: true })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Получить право', exact: true })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Сверить с файлом', exact: true })).toBeDisabled();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Скопировать черновик', exact: true })));
  expect(writeText).toHaveBeenCalledWith('my unsaved draft');
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(preparations);
  expect(api.listIdeRepositories).toHaveBeenCalledTimes(registryReads);
  expect(api.writeIdeFile).not.toHaveBeenCalled();
  expect(api.provisionIdeRuntime).not.toHaveBeenCalled();
});

it('freezes write permission while a runtime observation is pending and retains text on failed verification', async () => {
  const { input } = await openDraft();
  let fail;
  api.getIdeRuntime.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
  fireEvent.click(screen.getByRole('button', { name: 'Обновить IDE', exact: true }));
  await waitFor(() => expect(input).toHaveAttribute('readonly'));
  expect(input).toHaveValue('my unsaved draft');
  expect(screen.getByRole('button', { name: 'Записать в среду', exact: true })).toBeDisabled();
  await act(async () => fail(Error('PRIVATE_RUNTIME')));
  expect(input).toHaveValue('my unsaved draft');
  expect(input).toHaveAttribute('readonly');
  expect(screen.queryByText('PRIVATE_RUNTIME')).not.toBeInTheDocument();
  expect(api.writeIdeFile).not.toHaveBeenCalled();
});

it('requires an explicit reviewed base for a replacement generation and keeps a clean editor copy recoverable', async () => {
  const { input, navigation } = await openDraft('old');
  api.readIdeTree.mockResolvedValue({ repository_id: repo, generation: 'c'.repeat(64), entries: [{ path: 'main.py', type: 'file', size: 7, incomplete: false }], truncated: false });
  api.readIdeFile.mockResolvedValue({ repository_id: repo, generation: 'c'.repeat(64), path: 'main.py', kind: 'text', content: 'current', size: 7, digest: 'd'.repeat(64), truncated: false });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Обновить IDE', exact: true })));
  expect(navigation).not.toHaveBeenCalled();
  expect(input).toHaveValue('old');
  expect(input).toHaveAttribute('readonly');
  expect(screen.getByRole('button', { name: 'Получить право', exact: true })).toBeDisabled();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Сверить с файлом', exact: true })));
  expect(input).toHaveValue('old');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Загрузить версию', exact: true })));
  expect(input).toHaveValue('current');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Получить право', exact: true })));
  expect(input).not.toHaveAttribute('readonly');
  expect(api.readIdeFile.mock.calls.at(-1)[3]).toBe('c'.repeat(64));
  expect(api.writeIdeFile).not.toHaveBeenCalled();
});

it('keeps reading and preparation distinct without exposing manual create/start flashes', async () => {
  let resolve;
  let resolvePrepare;
  api.listIdeRepositories.mockReturnValue(new Promise((done) => { resolve = done; }));
  api.prepareIdeWorkspace.mockReturnValue(new Promise(done => { resolvePrepare = done; }));
  show();
  expect(screen.getByText('Загружаю IDE…')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Обновить IDE', exact: true })).toBeDisabled();
  expect(screen.queryByText('Репозитории IDE')).not.toBeInTheDocument();
  await act(async () => resolve({ items: [], next_offset: null }));
  expect(screen.getByText('Подготавливаю проект и среду IDE…')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Создать проект', exact: true })).not.toBeInTheDocument();
  expect(api.registerIdeRepository).not.toHaveBeenCalled();
  expect(api.getIdeRuntime).not.toHaveBeenCalled();
  await act(async () => resolvePrepare(prepared()));
  expect(await screen.findByText('Среда доступна')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Запустить среду', exact: true })).not.toBeInTheDocument();
});

it('makes reading a file explicit and renders its text without interpreting HTML', async () => {
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Repo', state: 'registered' }], next_offset: null });
  api.getIdeRuntime.mockResolvedValue({ repository_id: repo, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } });
  api.readIdeTree.mockResolvedValue({ repository_id: repo, generation, entries: [{ path: 'main.py', type: 'file', size: 20, incomplete: false }], truncated: false });
  api.readIdeFile.mockResolvedValue({ repository_id: repo, generation, path: 'main.py', kind: 'text', content: '<script>PRIVATE</script>', size: 24, digest: 'b'.repeat(64), truncated: false });
  const view = show();
  const file = await screen.findByRole('button', { name: 'main.py', exact: true }, { timeout: 5000 });
  expect(api.readIdeFile).not.toHaveBeenCalled();
  await act(async () => fireEvent.click(file));
  expect(await screen.findByRole('region', { name: 'Код файла main.py' })).toHaveTextContent('<script>PRIVATE</script>');
  expect(view.container.querySelector('script')).toBeNull();
});

it('shows a bounded read failure, never a create action or private exception', async () => {
  api.listIdeRepositories.mockRejectedValue(new Error('PRIVATE_TRANSPORT_BODY'));
  show();
  expect(await screen.findByRole('alert')).not.toHaveTextContent('PRIVATE');
  expect(screen.getByRole('button', { name: 'Повторить чтение' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: /создать/i })).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Не удалось загрузить IDE' })).toBeVisible();
});

it('keeps explicit additional-project intent across lost ack and then prepares it automatically', async () => {
  const second = '00000000-0000-0000-0000-000000000002';
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Repo', state: 'registered' }], next_offset: null });
  api.registerIdeRepository.mockRejectedValueOnce(new Error('PRIVATE')).mockResolvedValueOnce({ repository_id: second, name: 'My repo', state: 'registered' });
  await act(async () => show());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Новый проект' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Новый проект' }));
  const name = await screen.findByLabelText('Название проекта');
  fireEvent.change(name, { target: { value: 'My repo' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Создать проект', exact: true })));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат не подтверждён');
  expect(name).toHaveValue('My repo');
  expect(name).toHaveAttribute('readonly');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Повторить создание', exact: true })));
  expect(api.registerIdeRepository.mock.calls[1][1]).toEqual(api.registerIdeRepository.mock.calls[0][1]);
  expect(api.registerIdeRepository.mock.calls[0][1]).toMatchObject({ name: 'My repo', create_thread_if_missing: true });
  expect(api.provisionIdeRuntime).not.toHaveBeenCalled();
  await screen.findByText('Среда доступна');
  expect(api.prepareIdeWorkspace.mock.calls.map(call => call[1])).toEqual([repo, second]);
  expect(screen.queryByRole('button', { name: 'Запустить среду', exact: true })).not.toBeInTheDocument();
});

it('clones a nonempty repository into one separate project without manual registration', async () => {
  const second = '00000000-0000-0000-0000-000000000002';
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Original', state: 'registered' }], next_offset: null });
  api.operateIdeGit.mockImplementation((thread, id, data) => data.operation === 'clone'
    ? Promise.reject({ code: 'ide_git_not_empty' })
    : Promise.resolve({ repository_id: id, generation, initialized: true, branch: 'main' }));
  api.cloneIdeRepository.mockResolvedValue({ state: 'complete', repository: { repository_id: second, name: 'Clone', state: 'registered' } });
  await act(async () => show());
  fireEvent.click(screen.getByRole('button', { name: 'Клонировать по ссылке', exact: true }));
  fireEvent.change(screen.getByLabelText('Ссылка на репозиторий'), { target: { value: 'https://github.com/owner/repo' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Клонировать', exact: true })));
  expect(api.cloneIdeRepository).toHaveBeenCalledTimes(1);
  expect(api.cloneIdeRepository.mock.calls[0][1]).toMatchObject({ source_repository_id: repo });
  expect(api.prepareIdeWorkspace.mock.calls.at(-1)[1]).toBe(second);
  expect(api.registerIdeRepository).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog', { name: 'Клонировать репозиторий', exact: true })).not.toBeInTheDocument();
});

it('restores a reserved clone in the selected destination without a registration or legacy Git clone', async () => {
  const source = '00000000-0000-0000-0000-000000000002';
  const attempt = { intent_id: '10000000-0000-0000-0000-000000000002', source_repository_id: source,
    repository: { repository_id: repo, name: 'Destination', state: 'registered' }, state: 'preparing',
    request: { origin: 'https://github.com/owner/repo.git', branch: 'main' } };
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Destination', state: 'registered' }], next_offset: null });
  api.getIdeCloneRecovery.mockResolvedValue({ attempt });
  api.getIdeClone.mockResolvedValue({ repository: attempt.repository, state: 'preparing' });
  api.cloneIdeRepository.mockImplementation(async () => {
    api.getIdeCloneRecovery.mockResolvedValue({ attempt: { ...attempt, state: 'complete' } });
    return { repository: attempt.repository, state: 'complete' };
  });
  await act(async () => show());
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Состояние IDE', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Продолжить…', exact: true }));
  expect(screen.getByLabelText('Ссылка на репозиторий')).toHaveValue(attempt.request.origin);
  expect(screen.getByLabelText('Ссылка на репозиторий')).toHaveAttribute('readonly');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Продолжить попытку', exact: true })));
  expect(api.cloneIdeRepository.mock.calls[0][1]).toEqual({ intent_id: attempt.intent_id, source_repository_id: source, ...attempt.request });
  expect(api.registerIdeRepository).not.toHaveBeenCalled();
  expect(api.operateIdeGit.mock.calls.every(call => call[2].operation === 'status')).toBe(true);
  expect(screen.queryByRole('dialog', { name: 'Клонировать репозиторий', exact: true })).not.toBeInTheDocument();
});

it('validates the name before dispatch and focuses the field', async () => {
  api.listIdeRepositories.mockResolvedValue({ items: [{ repository_id: repo, name: 'Repo', state: 'registered' }], next_offset: null });
  show();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Новый проект' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Новый проект' }));
  const create = await screen.findByRole('button', { name: 'Создать проект', exact: true });
  await act(async () => fireEvent.click(create));
  expect(api.registerIdeRepository).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Название проекта')).toHaveFocus();
  expect(screen.getByLabelText('Название проекта')).toHaveAttribute('aria-invalid', 'true');
});

it('shows loading rather than another black canvas while retrying the initial error', async () => {
  let resolve;
  api.listIdeRepositories.mockRejectedValueOnce(new Error('PRIVATE')).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  show();
  const retry = await screen.findByRole('button', { name: 'Повторить чтение' });
  fireEvent.click(retry);
  expect(screen.getByText('Загружаю IDE…')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Создать проект', exact: true })).not.toBeInTheDocument();
  await act(async () => resolve({ items: [], next_offset: null }));
  expect(await screen.findByText('Среда доступна')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Создать проект', exact: true })).not.toBeInTheDocument();
});
