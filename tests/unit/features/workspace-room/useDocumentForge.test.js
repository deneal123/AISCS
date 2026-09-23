import { act, renderHook, waitFor } from '@testing-library/react';
import {
  acquireWorkspaceLease,
  activateDocumentVendorProfile,
  applyDocumentVendorOverlay,
  getDocumentBuild,
  getDocumentProfiles,
  getDocumentProject,
  releaseWorkspaceLease,
  startDocumentBuild,
} from '@api/chat';
import { useDocumentForge } from '../../../../src/features/workspace-room/model/useDocumentForge';

jest.mock('@api/chat', () => ({
  acquireWorkspaceLease: jest.fn(),
  activateDocumentVendorProfile: jest.fn(),
  applyDocumentVendorOverlay: jest.fn(),
  getDocumentBuild: jest.fn(),
  getDocumentProfiles: jest.fn(),
  getDocumentProject: jest.fn(),
  releaseWorkspaceLease: jest.fn(),
  startDocumentBuild: jest.fn(),
}));

const profiles = [
  {
    profile_id: 'generic_document',
    label: 'Универсальный документ',
    paper: 'a4',
    orientation: 'portrait',
  },
  {
    profile_id: 'beamer_16_9',
    label: 'Презентация 16:9',
    paper: 'screen',
    orientation: 'landscape',
  },
];

const project = {
  path: 'documents/current',
  mode: 'draft',
  locale: 'ru-RU',
  profile: profiles[0],
  latest_build: null,
};

const renderDocumentForge = () => renderHook(() => useDocumentForge({
  threadId: 'thread-1',
  workspace: {
    state: 'ready',
    revision: 'revision-1',
    entries: [{ path: 'documents/current/document.toml' }],
  },
  library: {
    state: 'ready',
    items: [{ file_id: 'vendor-file-1', name: 'publisher.zip', availability: 'ready' }],
  },
  selectedPath: 'documents/current/main.tex',
  refreshSnapshot: jest.fn(),
  notify: jest.fn(),
  onOpenSource: jest.fn(),
}));

describe('useDocumentForge', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getDocumentProfiles.mockResolvedValue({ profiles });
    getDocumentProject.mockResolvedValue(project);
    acquireWorkspaceLease.mockResolvedValue({ fence: 7 });
    releaseWorkspaceLease.mockResolvedValue({});
  });

  it('keeps an explicitly selected profile instead of reloading the current one', async () => {
    const { result } = renderDocumentForge();

    await waitFor(() => expect(result.current.project?.path).toBe('documents/current'));

    act(() => result.current.setSelectedProfile('beamer_16_9'));

    expect(result.current.selectedProfile).toBe('beamer_16_9');
    expect(result.current.targetPath).toBe('documents/current-beamer_16_9');
    expect(getDocumentProject).toHaveBeenCalledTimes(1);
  });

  it('finishes a final build at visual_pending without polling forever', async () => {
    startDocumentBuild.mockResolvedValue({
      build_id: 'build-1',
      state: 'building',
      final: true,
    });
    getDocumentBuild.mockResolvedValue({
      build_id: 'build-1',
      state: 'visual_pending',
      final: true,
      artifacts: [{ artifact_id: 'pdf-1', role: 'pdf' }],
    });
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.project?.path).toBe('documents/current'));

    let completed;
    await act(async () => {
      completed = await result.current.buildProject(true);
    });

    expect(completed?.state).toBe('visual_pending');
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
    expect(result.current.busy).toBe('');
    expect(releaseWorkspaceLease).toHaveBeenCalledWith(
      'thread-1',
      'documents/current',
      7,
      expect.any(Object),
    );
  });

  it('installs a selected Library vendor ZIP through the project lease', async () => {
    applyDocumentVendorOverlay.mockResolvedValue({
      outcome: 'imported',
      revision: 'revision-2',
      overlay: { package_id: 'publisher-kit', version: '1.0' },
    });
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.project?.path).toBe('documents/current'));

    let installed;
    await act(async () => {
      installed = await result.current.applyVendorOverlay();
    });

    expect(installed?.outcome).toBe('imported');
    expect(applyDocumentVendorOverlay).toHaveBeenCalledWith(
      'thread-1',
      'vendor-file-1',
      {
        path: 'documents/current',
        expected_revision: 'revision-1',
        fence: 7,
      },
      expect.any(Object),
    );
    expect(releaseWorkspaceLease).toHaveBeenCalledWith(
      'thread-1',
      'documents/current',
      7,
      expect.any(Object),
    );
  });

  it('activates a v2 vendor format by cloning the project under the same lease', async () => {
    getDocumentProject.mockResolvedValue({
      ...project,
      vendor_overlays: [{
        package_id: 'publisher-kit',
        version: '2.0',
        profile_available: true,
      }],
    });
    activateDocumentVendorProfile.mockResolvedValue({
      outcome: 'cloned',
      path: 'documents/current-publisher-kit',
      content_status: 'copied',
      revision: 'revision-2',
    });
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.selectedVendorPackage).toBe('publisher-kit'));

    await act(async () => {
      await result.current.activateVendorProfile();
    });

    expect(activateDocumentVendorProfile).toHaveBeenCalledWith(
      'thread-1',
      'publisher-kit',
      {
        path: 'documents/current',
        target_path: 'documents/current-publisher-kit',
        expected_revision: 'revision-1',
        fence: 7,
      },
      expect.any(Object),
    );
  });
});
