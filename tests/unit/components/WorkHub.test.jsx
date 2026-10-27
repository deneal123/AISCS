import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import WorkHubComponent from '../../../src/features/workspace-room/components/WorkHub';

// The sidebar owns opening; this harness supplies that controlled-owner seam.
function WorkHub(props) {
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  return <><button onClick={() => setLibraryOpen(true)}>Библиотека</button>
    <WorkHubComponent {...props} libraryOpen={libraryOpen} onLibraryClose={() => setLibraryOpen(false)} /></>;
}

const fail = (status) => Object.assign(new Error('unavailable'), { status });

function mockApi({ work, library = work?.library || { items: [] }, overrides = {} }) {
  jest.doMock('@api/chat', () => ({
    getWorkHub: jest.fn(() => (work instanceof Error ? Promise.reject(work) : Promise.resolve(work))),
    getAccountWorkLibrary: jest.fn(() => Promise.resolve(library)),
    getWorkspaceHistory: jest.fn(() => Promise.resolve({ entries: [] })),
    getWorkspaceIssues: jest.fn(() => Promise.resolve({ issues: [] })),
    ...overrides,
  }), { virtual: true });
}

describe('WorkHub', () => {
  beforeEach(() => jest.resetModules());

  it('сбрасывает вкладку контекста при смене треда, но не при обновлении', async () => {
    mockApi({ work: {
      workspace: { state: 'ready', entries: [], revision: 'r1' },
      room: {}, library: { state: 'ready', items: [] },
    } });
    let view;
    await act(async () => {
      view = render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>);
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Контекст', exact: true }));
    fireEvent.click(screen.getByRole('tab', { name: 'История', exact: true }));
    await act(async () => view.rerender(
      <ChakraProvider><WorkHub threadId="t-1" invalidationVersion={1} /></ChakraProvider>,
    ));
    expect(screen.getByRole('tab', { name: 'История', exact: true }))
      .toHaveAttribute('aria-selected', 'true');
    await act(async () => view.rerender(
      <ChakraProvider><WorkHub threadId="t-2" /></ChakraProvider>,
    ));
    expect(screen.getByRole('tab', { name: 'Задачи', exact: true }))
      .toHaveAttribute('aria-selected', 'true');
  });

  it('сохраняет выбранный файл и retry intent при смене панели', async () => {
    const uploadFileToWorkspace = jest.fn()
      .mockRejectedValueOnce(fail(503))
      .mockResolvedValue({ outcome: 'library_saved', file: { file_id: 'source-1' } });
    mockApi({
      work: {
        workspace: { state: 'absent', entries: [], revision: '' },
        room: {}, library: { state: 'ready', items: [] },
      },
      overrides: { uploadFileToWorkspace },
    });
    let view;
    await act(async () => {
      view = render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>);
    });
    const file = new File(['body'], 'retry-source.txt');
    await act(async () => fireEvent.change(view.container.querySelector('input[type="file"]'), {
      target: { files: [file] },
    }));
    await screen.findByRole('button', { name: 'Проверить и повторить' });
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    expect(screen.getByText('retry-source.txt')).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Проверить и повторить' })));
    expect(uploadFileToWorkspace).toHaveBeenCalledTimes(2);
    expect(uploadFileToWorkspace.mock.calls[1][1]).toBe(file);
    expect(uploadFileToWorkspace.mock.calls[1][5].uploadIntentId)
      .toBe(uploadFileToWorkspace.mock.calls[0][5].uploadIntentId);
  });

  it('называет истёкшую sandbox истёкшей, а не пустым каталогом', async () => {
    mockApi({ work: fail(410) });
    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    expect(screen.getByText(/Срок рабочей среды истёк/i)).toBeInTheDocument();
    expect(screen.queryByText(/Каталог пока пуст/i)).not.toBeInTheDocument();
  });

  it('показывает библиотеку без URL и storage key', async () => {
    mockApi({ work: { workspace: { state: 'absent', entries: [], revision: '' }, room: {}, library: { items: [{ file_id: 'opaque-id', name: 'contract.docx', availability: 'ready' }] } } });
    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    await waitFor(() => expect(screen.getByText('contract.docx')).toBeInTheDocument());
    expect(document.body.textContent).not.toContain('https://');
    expect(screen.getByRole('button', { name: /Создать и добавить/i })).toBeEnabled();
  });

  it('при несохранённом чате показывает библиотеку и не создаёт sandbox', async () => {
    mockApi({
      work: fail(404),
      library: { items: [{ file_id: 'opaque-id', name: 'library-only.pdf', availability: 'ready' }] },
    });
    await act(async () => render(<ChakraProvider><WorkHub threadId="draft-thread" /></ChakraProvider>));
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    await waitFor(() => expect(screen.getByText('library-only.pdf')).toBeInTheDocument());
    expect(screen.getByText('Загрузка только в Библиотеку. Добавление в проект — отдельно.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Создать и добавить/i })).toBeDisabled();
  });

  it('переключает серверную страницу без накопления файлов', async () => {
    const getAccountWorkLibrary = jest.fn().mockResolvedValueOnce({
      items: [{ file_id: 'file-1', name: 'newer.txt', availability: 'ready' }], next_offset: 10,
    }).mockResolvedValue({
      state: 'ready',
      items: [{ file_id: 'file-2', name: 'older.txt', availability: 'ready' }],
      next_cursor: null,
      next_offset: null,
    });
    mockApi({
      work: {
        workspace: { state: 'absent', entries: [], revision: '' },
        room: {},
        library: {
          state: 'ready',
          items: [{ file_id: 'file-1', name: 'newer.txt', availability: 'ready' }],
          next_cursor: 'cursor-1',
          next_offset: null,
        },
      },
      overrides: { getAccountWorkLibrary },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    await screen.findByText('newer.txt');
    fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница', exact: true }));

    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledWith({
      params: { limit: 10, offset: 10, q: '' },
      signal: expect.any(AbortSignal),
    }));
    expect(await screen.findByText('older.txt')).toBeInTheDocument();
    expect(screen.queryByText('newer.txt')).not.toBeInTheDocument();
  });

  it('обновляет текущую страницу при фоновом snapshot refresh', async () => {
    const base = {
      workspace: { state: 'absent', entries: [], revision: '' },
      room: {},
      library: {
        state: 'ready',
        items: [{ file_id: 'file-1', name: 'newer.txt', availability: 'ready' }],
        next_cursor: 'cursor-1',
      },
    };
    const getWorkHub = jest.fn()
      .mockResolvedValueOnce(base)
      .mockResolvedValue({
        ...base,
        library: {
          ...base.library,
          items: [
            { file_id: 'file-0', name: 'fresh.txt', availability: 'ready' },
            ...base.library.items,
          ],
        },
      });
    mockApi({
      work: base,
      overrides: {
        getWorkHub,
        getAccountWorkLibrary: jest.fn().mockResolvedValueOnce({
          items: [{ file_id: 'file-1', name: 'newer.txt' }], next_offset: 10,
        }).mockResolvedValue({
          state: 'ready',
          items: [{ file_id: 'file-2', name: 'older.txt', availability: 'ready' }],
          next_cursor: null,
        }),
      },
    });

    let view;
    await act(async () => {
      view = render(<ChakraProvider><WorkHub threadId="t-1" invalidationVersion={0} /></ChakraProvider>);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    await screen.findByText('newer.txt');
    fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница', exact: true }));
    await screen.findByText('older.txt');

    view.rerender(<ChakraProvider><WorkHub threadId="t-1" invalidationVersion={1} /></ChakraProvider>);
    expect(await screen.findByText('older.txt')).toBeInTheDocument();
    expect(screen.queryByText('newer.txt')).not.toBeInTheDocument();
  });

  it('оставляет bounded copy outcome рядом с занятым library-файлом', async () => {
    mockApi({
      work: {
        workspace: { state: 'ready', entries: [], history: [], revision: 'r1' },
        room: { state: 'ready', control: { state: 'running' } },
        library: {
          state: 'ready',
          items: [{ file_id: 'busy-file', name: 'busy.txt', availability: 'ready' }],
        },
      },
      overrides: {
        acquireWorkspaceLease: jest.fn(() => Promise.reject(fail(423))),
      },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    fireEvent.click(await screen.findByRole('button', { name: /Добавить в рабочее место/i }));

    expect(await screen.findByText('занято агентом')).toBeInTheDocument();
    expect(screen.getByText('busy.txt')).toBeInTheDocument();
  });

  it('держит мобильные разделы в обычном потоке и даёт повторить недоступную среду', async () => {
    mockApi({ work: fail(503) });
    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));

    expect(screen.getByTestId('work-mobile-tabs')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Повторить проверку/i })).toBeInTheDocument();
  });

  it('связывает мобильные вкладки с настоящими сохраняемыми панелями', async () => {
    mockApi({ work: fail(503) });
    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    const tablist = screen.getByRole('tablist', { name: 'Разделы работы' });
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    expect(tabs).toHaveLength(2);
    const panels = tabs.map((tab) => document.getElementById(tab.getAttribute('aria-controls')));
    panels.forEach((panel, index) => {
      expect(panel).toHaveAttribute('role', 'tabpanel');
      expect(panel).toHaveAttribute('aria-labelledby', tabs[index].id);
    });
    expect(panels[0]).toBeVisible();
    fireEvent.click(tabs[1]);
    expect(panels[0]).not.toBeVisible();
    expect(panels[1]).toBeVisible();
    fireEvent.click(tabs[0]);
    expect(panels[0]).toBeVisible();
    panels.forEach((panel) => expect(panel).toBeInTheDocument());
  });

  it('при занятой lease читает файл без права перезаписи', async () => {
    const acquire = jest.fn(() => Promise.reject(fail(409)));
    const read = jest.fn(() => Promise.resolve({ content: 'server text', revision: 'r1' }));
    mockApi({
      work: {
        workspace: { state: 'ready', entries: [{ type: 'file', path: 'note.txt' }], history: [], revision: 'r1' },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [] },
      },
      overrides: { acquireWorkspaceLease: acquire, getWorkspaceFile: read },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: /note.txt/i }));

    const editor = await screen.findByLabelText(/Содержимое note.txt/i);
    expect(editor).toHaveValue('server text');
    expect(editor).toHaveAttribute('readonly');
    expect(editor).toHaveAttribute('aria-readonly', 'true');
    expect(screen.getByText(/уже редактируется в другом окне/i)).toBeInTheDocument();
  });

  it('повторный выбор открытого файла не перечитывает его и возвращает фокус в редактор', async () => {
    const acquire = jest.fn(() => Promise.resolve({ fence: 5 }));
    const read = jest.fn(() => Promise.resolve({ content: 'draft source', revision: 'r1' }));
    mockApi({
      work: {
        workspace: { state: 'ready', entries: [{ type: 'file', path: 'note.txt' }], history: [], revision: 'r1' },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [] },
      },
      overrides: { acquireWorkspaceLease: acquire, getWorkspaceFile: read },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    const treeItem = await screen.findByRole('button', { name: /note.txt/i });
    fireEvent.click(treeItem);
    const editor = await screen.findByLabelText(/Содержимое note.txt/i);
    fireEvent.change(editor, { target: { value: 'local draft' } });
    treeItem.focus();
    fireEvent.click(treeItem);

    expect(acquire).toHaveBeenCalledTimes(1);
    expect(read).toHaveBeenCalledTimes(1);
    expect(editor).toHaveValue('local draft');
    await waitFor(() => expect(editor).toHaveFocus());
  });

  it('освобождает только что полученную lease, если чтение файла не удалось', async () => {
    const release = jest.fn(() => Promise.resolve({ released: true }));
    mockApi({
      work: {
        workspace: { state: 'ready', entries: [{ type: 'file', path: 'broken.txt' }], history: [], revision: 'r1' },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [] },
      },
      overrides: {
        acquireWorkspaceLease: jest.fn(() => Promise.resolve({ fence: 8 })),
        getWorkspaceFile: jest.fn(() => Promise.reject(fail(503))),
        releaseWorkspaceLease: release,
      },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: /broken.txt/i }));

    await waitFor(() => expect(release).toHaveBeenCalledWith(
      't-1',
      'broken.txt',
      8,
      { actorSession: expect.any(String) },
    ));
    expect(await screen.findByText(/Не удалось прочитать файл/i)).toBeInTheDocument();
  });

  it('не теряет dirty draft после revision conflict', async () => {
    const read = jest.fn()
      .mockResolvedValueOnce({ content: 'old', revision: 'r1' })
      .mockResolvedValueOnce({ content: 'current', revision: 'r2' });
    mockApi({
      work: {
        workspace: { state: 'ready', entries: [{ type: 'file', path: 'note.txt' }], history: [], revision: 'r1' },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [] },
      },
      overrides: {
        acquireWorkspaceLease: jest.fn(() => Promise.resolve({ fence: 7 })),
        getWorkspaceFile: read,
        writeWorkspaceFile: jest.fn(() => Promise.reject(fail(409))),
        getWorkspaceDiff: jest.fn(() => Promise.resolve({ diff: '-old\n+current' })),
      },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: /note.txt/i }));
    const editor = await screen.findByLabelText(/Содержимое note.txt/i);
    fireEvent.change(editor, { target: { value: 'my unsaved draft' } });
    fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/i }));

    await waitFor(() => expect(screen.getByText(/Версия файла изменилась/i)).toBeInTheDocument());
    expect(editor).toHaveValue('my unsaved draft');
    expect(screen.getByRole('button', { name: /Скопировать мои изменения/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Загрузить актуальную/i })).toBeEnabled();
  });

  it('сохраняет правку по Ctrl+S и показывает provenance', async () => {
    const writeWorkspaceFile = jest.fn(() => Promise.resolve({ revision: 'r2', fence: 4 }));
    mockApi({
      work: {
        workspace: {
          state: 'ready',
          entries: [{ type: 'file', path: 'note.txt' }],
          history: [],
          revision: 'r1',
        },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [] },
      },
      overrides: {
        acquireWorkspaceLease: jest.fn(() => Promise.resolve({ fence: 4 })),
        getWorkspaceFile: jest.fn(() => Promise.resolve({ content: 'old', revision: 'r1' })),
        writeWorkspaceFile,
      },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: /note.txt/i }));
    const editor = await screen.findByLabelText(/Содержимое note.txt/i);
    fireEvent.change(editor, { target: { value: 'new' } });
    fireEvent.keyDown(editor, { key: 's', ctrlKey: true });

    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledWith(
      't-1',
      'note.txt',
      'new',
      'r1',
      4,
      { actorSession: expect.any(String) },
    ));
    expect(screen.getByTestId('work-status-rail')).toHaveTextContent('Источник');
    expect(screen.getByTestId('work-status-rail')).toHaveTextContent('Версия');
  });

  it('копирует Library с подтверждённой revision редактора при запаздывающем snapshot', async () => {
    const copyLibraryFileToWorkspace = jest.fn(() => Promise.resolve({ outcome: 'kept', revision: 'r2' }));
    mockApi({
      work: {
        workspace: { state: 'ready', entries: [{ type: 'file', path: 'note.txt' }], history: [], revision: 'r1' },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [{ file_id: 'owned-zip', name: 'source.zip', availability: 'ready' }] },
      },
      overrides: {
        acquireWorkspaceLease: jest.fn(() => Promise.resolve({ fence: 7 })),
        releaseWorkspaceLease: jest.fn(() => Promise.resolve({ released: true })),
        getWorkspaceFile: jest.fn(() => Promise.resolve({ content: 'old', revision: 'r1' })),
        writeWorkspaceFile: jest.fn(() => Promise.resolve({ revision: 'r2', fence: 7 })),
        copyLibraryFileToWorkspace,
      },
    });
    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: /note.txt/i }));
    fireEvent.change(await screen.findByLabelText(/Содержимое note.txt/i), { target: { value: 'new' } });
    fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/i }));
    await screen.findByText('Сохранено.');
    fireEvent.click(screen.getByRole('button', { name: 'Библиотека', exact: true }));
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить в рабочее место' }));
    await waitFor(() => expect(copyLibraryFileToWorkspace).toHaveBeenCalledWith(
      't-1', 'owned-zip', 'r2', 7, { actorSession: expect.any(String) },
    ));
    expect(screen.getByLabelText(/Содержимое note.txt/i)).toHaveValue('new');
  });

  it('использует revision последней записи редактора при откате', async () => {
    const revertWorkspace = jest.fn(() => Promise.resolve({ reverted: true, revision: 'r3' }));
    mockApi({
      work: {
        workspace: {
          state: 'ready',
          entries: [{ type: 'file', path: 'note.txt' }],
          history: [
            { ref: 'r2', message: 'user_edit' },
            { ref: 'r1', message: 'import' },
          ],
          revision: 'r1',
        },
        room: { state: 'ready', control: { state: 'running' } },
        library: { state: 'ready', items: [] },
      },
      overrides: {
        acquireWorkspaceLease: jest.fn(() => Promise.resolve({ fence: 7 })),
        releaseWorkspaceLease: jest.fn(() => Promise.resolve({ released: true })),
        getWorkspaceFile: jest.fn(() => Promise.resolve({ content: 'old', revision: 'r1' })),
        writeWorkspaceFile: jest.fn(() => Promise.resolve({ revision: 'r2', fence: 7 })),
        getWorkspaceDiff: jest.fn(() => Promise.resolve({ diff: '-old\n+new' })),
        revertWorkspace,
      },
    });

    await act(async () => render(<ChakraProvider><WorkHub threadId="t-1" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: /note.txt/i }));
    fireEvent.change(await screen.findByLabelText(/Содержимое note.txt/i), {
      target: { value: 'new' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/i }));
    await screen.findByText('Сохранено.');

    fireEvent.click(screen.getByRole('tab', { name: 'Контекст' }));
    fireEvent.click(screen.getByRole('tab', { name: 'История' }));
    fireEvent.click((await screen.findAllByRole('button', { name: 'Показать diff' }))[1]);
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить откат' }));

    await waitFor(() => expect(revertWorkspace).toHaveBeenCalledWith(
      't-1',
      'r1',
      'r2',
      '',
      { actorSession: expect.any(String) },
    ));
  }, 10000);

  it('игнорирует поздний snapshot предыдущего треда', async () => {
    let resolveOld;
    const old = new Promise((resolve) => { resolveOld = resolve; });
    const getWorkHub = jest.fn((threadId) => threadId === 'old-thread'
      ? old
      : Promise.resolve({
        workspace: { state: 'absent', entries: [], history: [], revision: '' },
        room: { state: 'absent' },
        library: { state: 'ready', items: [{ file_id: 'new-id', name: 'new.txt' }] },
      }));
    mockApi({ work: {}, library: { items: [{ file_id: 'new-id', name: 'new.txt' }] }, overrides: { getWorkHub } });
    const rendered = render(<ChakraProvider><WorkHub threadId="old-thread" /></ChakraProvider>);

    await act(async () => rendered.rerender(<ChakraProvider><WorkHub threadId="new-thread" /></ChakraProvider>));
    fireEvent.click(await screen.findByRole('button', { name: 'Библиотека', exact: true }));
    expect(await screen.findByText('new.txt')).toBeInTheDocument();
    await act(async () => resolveOld({
      workspace: { state: 'absent', entries: [], history: [], revision: '' },
      room: { state: 'absent' },
      library: { state: 'ready', items: [{ file_id: 'old-id', name: 'old.txt' }] },
    }));

    expect(screen.queryByText('old.txt')).not.toBeInTheDocument();
    expect(screen.getByText('new.txt')).toBeInTheDocument();
  });
});
