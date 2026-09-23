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

  it('opens a source diagnostic through the document lifecycle', () => {
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
                { severity: 'error', code: 'compile_failed', path: 'main.tex', line: 14 },
              ],
            },
          }}
        />
      </ChakraProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /main\.tex:14/i }));

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
