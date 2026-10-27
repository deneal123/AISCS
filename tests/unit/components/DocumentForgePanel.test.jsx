import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { DocumentForgePanel } from '@features/workspace-room/components/DocumentForgePanel';

const baseDocument = {
  profiles: [
    {
      profile_id: 'generic_article',
      label: 'Научная статья',
      paper: 'a4',
      orientation: 'portrait',
    },
  ],
  selectedProfile: 'generic_article',
  setSelectedProfile: jest.fn(),
  selectedMode: 'draft',
  setSelectedMode: jest.fn(),
  selectedLocale: 'ru-RU',
  setSelectedLocale: jest.fn(),
  vendorFiles: [
    { file_id: 'vendor-file-1', name: 'publisher.zip', availability: 'ready' },
  ],
  selectedVendorFile: 'vendor-file-1',
  setSelectedVendorFile: jest.fn(),
  applyVendorOverlay: jest.fn(),
  activateVendorProfile: jest.fn(),
  project: {
    path: 'documents/paper',
    mode: 'draft',
    locale: 'ru-RU',
    profile: { profile_id: 'generic_article', label: 'Научная статья' },
    vendor_overlays: [
      {
        package_id: 'publisher-kit',
        version: '1.0',
        license: 'LPPL-1.3c',
        trusted: false,
      },
    ],
  },
  busy: '',
  buildProject: jest.fn(),
  cancelBuild: jest.fn(),
  openPreview: jest.fn(),
  publish: jest.fn(),
};

describe('DocumentForgePanel', () => {
  it('shows formatting without project creation, authoring, build or delivery controls', () => {
    render(<ChakraProvider><DocumentForgePanel section="formatting" document={{
      ...baseDocument, previewUrl: 'blob:owned-preview',
      build: { state: 'preview_ready', artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }] },
    }} /></ChakraProvider>);
    expect(screen.getByText('Параметры документа')).toBeInTheDocument();
    expect(screen.queryByLabelText('Параметры выбранного профиля')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Профиль PDF-документа')).toBeInTheDocument();
    expect(screen.getByText('Шаблон издателя')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Применить настройки', exact: true })).toBeDisabled();
    fireEvent.click(screen.getByText('Шаблон издателя'));
    expect(screen.getByRole('button', { name: 'Добавить в проект' })).toBeInTheDocument();
    expect(screen.queryByText('Document Forge')).not.toBeInTheDocument();
    expect(screen.queryByText('Структурированный документ')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать проект', exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Собрать черновик' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Этапы подготовки документа')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
  });

  it('does not repeat project creation inside formatting before a project exists', () => {
    render(<ChakraProvider><DocumentForgePanel section="formatting" document={{
      ...baseDocument, project: null, createProject: jest.fn(),
    }} /></ChakraProvider>);
    expect(screen.getByText(/Сначала создайте или выберите PDF-проект/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Создать проект', exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('keeps explicit settings application and blocks a second application while busy', () => {
    const applyProfile = jest.fn();
    const document = { ...baseDocument, selectedMode: 'submission', applyProfile };
    const view = render(<ChakraProvider><DocumentForgePanel section="formatting" document={document} /></ChakraProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Применить настройки', exact: true }));
    expect(applyProfile).toHaveBeenCalledTimes(1);
    view.rerender(<ChakraProvider><DocumentForgePanel section="formatting" document={{ ...document, busy: 'profile' }} /></ChakraProvider>);
    expect(screen.getByRole('button', { name: /Применить настройки/ })).toBeDisabled();
  });

  it('keeps project creation in its dedicated empty editor state', () => {
    const createProject = jest.fn();
    render(<ChakraProvider><DocumentForgePanel section="create" document={{
      ...baseDocument, project: null, createProject,
    }} /></ChakraProvider>);
    expect(screen.getByText('Новый PDF-проект')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Создать проект', exact: true }));
    expect(createProject).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Document Forge')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Этапы подготовки документа')).not.toBeInTheDocument();
  });

  it('offers a read-only status retry and blocks uncertain publication', () => {
    const checkPublication = jest.fn();
    const publish = jest.fn();
    render(<ChakraProvider><DocumentForgePanel document={{
      ...baseDocument, publicationError: true, checkPublication, publish,
      build: {
        build_id: 'build-1', state: 'ready', final: true,
        artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }],
      },
    }} /></ChakraProvider>);
    expect(screen.getByLabelText('Состояние сохранения документа'))
      .toHaveTextContent('Оно могло завершиться');
    const check = screen.getByRole('button', { name: 'Проверить сохранение' });
    expect(check).toHaveAttribute('data-toast-protected-actions');
    expect(screen.getByRole('button', { name: 'Собрать черновик' }).parentElement)
      .toHaveAttribute('data-toast-protected-actions');
    expect(screen.getByRole('button', { name: 'Сохранить в Библиотеку' }).parentElement)
      .toHaveAttribute('data-toast-protected-actions');
    fireEvent.click(check);
    expect(checkPublication).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Сохранить в Библиотеку' })).toBeDisabled();
    expect(publish).not.toHaveBeenCalled();
  });

  it('keeps status recovery available while checking without changing its label', () => {
    render(<ChakraProvider><DocumentForgePanel document={{
      ...baseDocument, publicationChecking: true, checkPublication: jest.fn(),
    }} /></ChakraProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('Редактор остаётся доступен');
    expect(screen.getByRole('button', { name: 'Проверить сохранение' })).toBeDisabled();
  });

  it.each(['terminal', 'delivered'])('does not offer a repeated mutation for %s', (state) => {
    render(<ChakraProvider><DocumentForgePanel document={{
      ...baseDocument,
      build: { state: 'ready', final: true, publication_state: state,
        artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }] },
    }} /></ChakraProvider>);
    expect(screen.getByRole('button', { name: 'Сохранить в Библиотеку' })).toBeDisabled();
    if (state === 'terminal') {
      expect(screen.getByLabelText('Состояние сохранения документа'))
        .toHaveTextContent('Финал не удалось сохранить');
      expect(screen.getByLabelText('Состояние сохранения документа'))
        .toHaveTextContent('Библиотеку в левой панели');
    }
    expect(screen.queryByRole('button', { name: 'Проверить сохранение' })).not.toBeInTheDocument();
  });

  it('keeps the panel mounted but removes an inactive preview without reopening it', () => {
    const documentState = { ...baseDocument, previewUrl: 'blob:owned-preview' };
    const view = render(<ChakraProvider><DocumentForgePanel document={documentState} /></ChakraProvider>);
    expect(screen.getByTitle('Предпросмотр PDF')).toHaveAttribute('src', 'blob:owned-preview');
    view.rerender(<ChakraProvider><DocumentForgePanel document={documentState} previewVisible={false} /></ChakraProvider>);
    expect(screen.queryByTitle('Предпросмотр PDF')).not.toBeInTheDocument();
    expect(screen.getByText('Научная статья · Черновик')).toBeInTheDocument();
    view.rerender(<ChakraProvider><DocumentForgePanel document={documentState} /></ChakraProvider>);
    expect(screen.getByTitle('Предпросмотр PDF')).toHaveAttribute('src', 'blob:owned-preview');
    expect(documentState.openPreview).not.toHaveBeenCalled();
  });

  it.each([
    ['queued', 'ожидает запуска', 'не запускался'],
    ['preparing', 'ожидает запуска', 'не запускался'],
    ['building', 'выполняется', 'не запускался'],
    ['deterministic_audit', 'завершена', 'выполняется'],
    ['preview_ready', 'завершена', 'пройден'],
    ['visual_pending', 'завершена', 'пройден'],
    ['failed', 'состояние уточняется', 'состояние уточняется'],
    ['cancelled', 'состояние уточняется', 'состояние уточняется'],
    ['private_unknown_state', 'состояние уточняется', 'состояние уточняется'],
  ])('does not invent stage success for %s', (state, compilation, audit) => {
    render(<ChakraProvider><DocumentForgePanel document={{
      ...baseDocument, build: { state },
    }} /></ChakraProvider>);
    const pipeline = screen.getByLabelText('Этапы подготовки документа');
    expect(pipeline).toHaveTextContent(`Сборка${compilation}`);
    expect(pipeline).toHaveTextContent(`Технический аудит${audit}`);
    expect(document.body).not.toHaveTextContent('private_unknown_state');
  });

  it.each([
    ['draft', 'Черновик'], ['submission', 'Подача'], ['camera_ready', 'Финальная версия'],
    ['private_mode_marker', 'Режим уточняется'], [undefined, 'Режим уточняется'],
    ['toString', 'Режим уточняется'],
  ])('shows only a safe project mode for %s', (mode, label) => {
    render(<ChakraProvider><DocumentForgePanel document={{
      ...baseDocument, project: { ...baseDocument.project, mode },
    }} /></ChakraProvider>);
    expect(screen.getByText(`Научная статья · ${label}`)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('private_mode_marker');
  });

  it('renders bounded failure and diagnostic labels without raw codes', () => {
    render(
      <ChakraProvider>
        <DocumentForgePanel
          document={{
            ...baseDocument,
            build: {
              state: 'failed',
              failure_code: 'source_changed',
              diagnostics: [{ severity: 'error', code: 'private_raw_code' }],
            },
          }}
        />
      </ChakraProvider>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Исходники изменились');
    expect(screen.getByText('Требуется проверка документа')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('source_changed');
    expect(document.body).not.toHaveTextContent('private_raw_code');
  });

  it.each([
    ['compile_failed', 'LaTeX не удалось собрать'],
    ['unsupported_character', 'Шрифт или кодировка не поддерживает символ. Проверьте язык документа'],
  ])('opens a %s source diagnostic through the document lifecycle', (code, label) => {
    const openDiagnostic = jest.fn();
    render(
      <ChakraProvider>
        <DocumentForgePanel
          document={{
            ...baseDocument,
            openDiagnostic,
            build: {
              state: 'failed',
              failure_code: 'audit_failed',
              diagnostics: [
                { severity: 'error', code, path: 'main.tex', line: 14 },
              ],
            },
          }}
        />
      </ChakraProvider>,
    );

    const diagnostic = screen.getByRole('button', { name: /main\.tex:14/i });
    expect(diagnostic).toHaveTextContent(label);
    fireEvent.click(diagnostic);

    expect(openDiagnostic).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'main.tex', line: 14 }),
    );
  });

  it('offers visual audit and publication for a compiled final PDF', () => {
    const publish = jest.fn();
    render(
      <ChakraProvider>
        <DocumentForgePanel
          document={{
            ...baseDocument,
            publish,
            build: {
              build_id: 'build-1',
              state: 'visual_pending',
              final: true,
              publication_state: 'pending_audit',
              artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }],
            },
          }}
        />
      </ChakraProvider>,
    );

    expect(screen.getAllByText('Ожидает визуальной проверки')).not.toHaveLength(0);
    expect(screen.getByText(/перед публикацией нужна обязательная визуальная проверка/i))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Проверить и сохранить' })).toBeDisabled();
    expect(document.body).not.toHaveTextContent('pending_audit');
  });

  it('shows a safe publication failure without exposing its raw status', () => {
    render(
      <ChakraProvider>
        <DocumentForgePanel
          document={{
            ...baseDocument,
            build: {
              state: 'ready',
              final: true,
              publication_state: 'private_unknown_status',
              artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }],
            },
          }}
        />
      </ChakraProvider>,
    );

    expect(screen.getByLabelText('Этапы подготовки документа'))
      .toHaveTextContent('состояние уточняется');
    expect(document.body).not.toHaveTextContent('private_unknown_status');
  });

  it('offers an isolated Library vendor package without exposing transport data', () => {
    const applyVendorOverlay = jest.fn();
    render(
      <ChakraProvider>
        <DocumentForgePanel
          document={{
            ...baseDocument,
            applyVendorOverlay,
          }}
        />
      </ChakraProvider>,
    );

    expect(screen.getByText('Шаблон издателя')).toBeInTheDocument();
    expect(screen.getByText('publisher-kit')).toBeInTheDocument();
    expect(screen.getByText(/1\.0 · изолирован/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Добавить в проект' }));
    expect(applyVendorOverlay).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent('https://');
  });

  it('shows the semantic outline and opens only its managed source file', () => {
    const openDiagnostic = jest.fn();
    render(
      <ChakraProvider>
        <DocumentForgePanel
          document={{
            ...baseDocument,
            openDiagnostic,
            authoring: {
              state: 'ready',
              value: {
                authoring_version: 3,
                intent: {
                  kind: 'article',
                  title: 'Проверяемая статья',
                  audience: 'исследователи',
                  citation_policy: 'required',
                  legal_fields: [],
                },
                draft: {
                  title: 'Проверяемая статья',
                  blocks: [{ id: 'intro_block', kind: 'section', title: 'Введение' }],
                },
                block_files: { intro_block: 'content/001-intro_block.tex' },
              },
            },
          }}
        />
      </ChakraProvider>,
    );

    expect(screen.getByText('Проверяемая статья')).toBeInTheDocument();
    expect(screen.getByText('Структура · 1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Раздел: Введение' }));
    expect(openDiagnostic).toHaveBeenCalledWith({ path: 'content/001-intro_block.tex' });
  });
});
