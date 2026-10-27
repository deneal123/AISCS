import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import {
  acquireWorkspaceLease,
  createDocumentProject,
  saveDocumentDraft,
  applyDocumentProfile,
  activateDocumentVendorProfile,
  applyDocumentVendorOverlay,
  downloadDocumentArtifact,
  getDocumentBuild,
  getDocumentProfiles,
  getDocumentProject,
  getDocumentAuthoringState,
  releaseWorkspaceLease,
  publishDocumentArtifact,
  startDocumentBuild,
} from '@api/chat';
import { useDocumentForge } from '../../../../src/features/workspace-room/model/useDocumentForge';

jest.mock('@api/chat', () => ({
  acquireWorkspaceLease: jest.fn(),
  createDocumentProject: jest.fn(),
  saveDocumentDraft: jest.fn(),
  applyDocumentProfile: jest.fn(),
  activateDocumentVendorProfile: jest.fn(),
  applyDocumentVendorOverlay: jest.fn(),
  downloadDocumentArtifact: jest.fn(),
  getDocumentBuild: jest.fn(),
  getDocumentProfiles: jest.fn(),
  getDocumentProject: jest.fn(),
  getDocumentAuthoringState: jest.fn(),
  releaseWorkspaceLease: jest.fn(),
  publishDocumentArtifact: jest.fn(),
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

const renderDocumentForge = (overrides = {}) => renderHook(() => useDocumentForge({
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
  ...overrides,
}));

describe('useDocumentForge', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getDocumentProfiles.mockResolvedValue({ profiles });
    getDocumentProject.mockResolvedValue(project);
    acquireWorkspaceLease.mockResolvedValue({ fence: 7 });
    releaseWorkspaceLease.mockResolvedValue({});
  });

  it('creates after expiry only on explicit submission, with the fresh workspace revision', async () => {
    const path = 'documents/new-presentation';
    const prepareWorkspace = jest.fn().mockResolvedValue({ state: 'ready', revision: 'fresh-r1' });
    createDocumentProject.mockResolvedValue({ path, revision_changed: true, revision: 'fresh-r2' });
    saveDocumentDraft.mockResolvedValue({ authoring_version: 1 });
    const { result } = renderDocumentForge({ workspace: { state: 'expired', revision: 'old-r1', entries: [] } });
    await waitFor(() => expect(result.current.profilesState).toBe('ready'));
    expect(prepareWorkspace).not.toHaveBeenCalled();
    await act(async () => result.current.createProject({ path }));
    expect(createDocumentProject).not.toHaveBeenCalled();
    await act(async () => result.current.createProject({ path, profileId: 'beamer_16_9', initializeContent: true }, { prepareWorkspace }));
    expect(prepareWorkspace).toHaveBeenCalledTimes(1);
    expect(createDocumentProject).toHaveBeenCalledWith('thread-1', expect.objectContaining({
      path, profile_id: 'beamer_16_9', expected_revision: 'fresh-r1',
    }), expect.anything());
    expect(startDocumentBuild).not.toHaveBeenCalled();
  });

  it('does not write or acquire a lease when explicit workspace activation is unconfirmed', async () => {
    const prepareWorkspace = jest.fn().mockResolvedValue(null);
    const { result } = renderDocumentForge({ workspace: { state: 'expired', entries: [] } });
    await act(async () => result.current.createProject({ path: 'documents/new' }, { prepareWorkspace }));
    expect(prepareWorkspace).toHaveBeenCalledTimes(1);
    expect(acquireWorkspaceLease).not.toHaveBeenCalled();
    expect(createDocumentProject).not.toHaveBeenCalled();
  });

  it('recovers a failed format catalog explicitly without creating a document', async () => {
    getDocumentProfiles.mockRejectedValueOnce(new Error('unavailable'));
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.profilesState).toBe('unavailable'));
    expect(result.current.profiles).toEqual([]);
    await act(async () => result.current.loadProfiles());
    expect(result.current.profilesState).toBe('ready');
    expect(result.current.profiles).toEqual(profiles);
    expect(createDocumentProject).not.toHaveBeenCalled();
  });

  it('retains the acknowledged catalog across peer navigation but reloads for a different thread', async () => {
    const settings = { threadId: 'thread-1', active: true, workspace: { state: 'expired', entries: [] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.profilesState).toBe('ready'));
    act(() => result.current.setSelectedProfile('beamer_16_9'));
    rerender({ ...settings, active: false });
    rerender(settings);
    expect(getDocumentProfiles).toHaveBeenCalledTimes(1);
    expect(result.current.selectedProfile).toBe('beamer_16_9');
    expect(result.current.profiles).toEqual(profiles);
    rerender({ ...settings, threadId: 'thread-2' });
    await waitFor(() => expect(getDocumentProfiles).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.profilesState).toBe('ready'));
    expect(getDocumentProfiles.mock.calls[1][0]).toBe('thread-2');
    expect(createDocumentProject).not.toHaveBeenCalled();
    expect(acquireWorkspaceLease).not.toHaveBeenCalled();
  });

  it('restarts an interrupted catalog read and ignores its late response', async () => {
    let resolveRetired;
    getDocumentProfiles.mockImplementationOnce(() => new Promise((resolve) => { resolveRetired = resolve; }));
    const settings = { threadId: 'thread-1', active: true, workspace: { state: 'expired', entries: [] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(getDocumentProfiles).toHaveBeenCalledTimes(1));
    rerender({ ...settings, active: false });
    expect(getDocumentProfiles.mock.calls[0][1].signal.aborted).toBe(true);
    rerender(settings);
    await waitFor(() => expect(result.current.profilesState).toBe('ready'));
    expect(getDocumentProfiles).toHaveBeenCalledTimes(2);
    await act(async () => resolveRetired({ profiles: [{ profile_id: 'retired', label: 'Устаревший формат' }] }));
    expect(result.current.profiles).toEqual(profiles);
    expect(createDocumentProject).not.toHaveBeenCalled();
  });

  it('does not leave an interrupted explicit catalog refresh stuck in loading on return', async () => {
    const settings = { threadId: 'thread-1', active: true, workspace: { state: 'expired', entries: [] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.profilesState).toBe('ready'));
    let resolveRetired;
    getDocumentProfiles.mockImplementationOnce(() => new Promise((resolve) => { resolveRetired = resolve; }));
    let refresh;
    act(() => { refresh = result.current.loadProfiles(); });
    await waitFor(() => expect(getDocumentProfiles).toHaveBeenCalledTimes(2));
    rerender({ ...settings, active: false });
    rerender(settings);
    await waitFor(() => expect(result.current.profilesState).toBe('ready'));
    expect(getDocumentProfiles).toHaveBeenCalledTimes(3);
    await act(async () => { resolveRetired({ profiles: [] }); await refresh; });
    expect(result.current.profilesState).toBe('ready');
    expect(result.current.profiles).toEqual(profiles);
  });

  it('prepares a fresh presentation using the acknowledged revision and the original path lease', async () => {
    const path = 'documents/separate-presentation';
    createDocumentProject.mockResolvedValue({ path, revision_changed: true, revision: 'r2' });
    saveDocumentDraft.mockResolvedValue({ authoring_version: 1 });
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    await act(async () => result.current.createProject({ path, profileId: 'beamer_16_9', initializeContent: true }));
    expect(createDocumentProject).toHaveBeenCalledWith('thread-1', expect.objectContaining({
      path, profile_id: 'beamer_16_9', expected_revision: 'revision-1', fence: 7,
    }), expect.any(Object));
    expect(saveDocumentDraft).toHaveBeenCalledWith('thread-1', expect.objectContaining({
      path, expected_revision: 'r2', authoring_version: 0, draft_digest: null, fence: 7,
      draft: expect.objectContaining({ title: 'Новая презентация', blocks: [expect.objectContaining({ kind: 'slide' })] }),
    }), expect.any(Object));
  });

  it('reports source-only creation once without a contradictory success notification', async () => {
    const path = 'documents/source-only';
    const notify = jest.fn();
    createDocumentProject.mockResolvedValue({ path, revision_changed: true, revision: 'r2' });
    saveDocumentDraft.mockRejectedValueOnce(new Error('authoring_unavailable'));
    const { result } = renderDocumentForge({ notify });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    await act(async () => result.current.createProject({ path, initializeContent: true }));
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      status: 'warning', title: 'Проект создан, доступны исходники',
    }));
    expect(releaseWorkspaceLease).toHaveBeenCalledTimes(1);
  });

  it('recovers a lost create reply by reading its exact destination without another source write', async () => {
    const path = 'documents/recovered-presentation';
    const observed = { ...project, path, profile: profiles[1] };
    const notify = jest.fn();
    createDocumentProject.mockRejectedValueOnce(new Error('lost_reply'));
    const { result } = renderDocumentForge({ notify });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    getDocumentProject.mockResolvedValue(observed);
    let recovered;
    await act(async () => { recovered = await result.current.createProject({
      path, profileId: 'beamer_16_9', initializeContent: true,
    }); });
    expect(recovered.path).toBe(path);
    expect(result.current.selectedProject).toBe(path);
    expect(createDocumentProject).toHaveBeenCalledTimes(1);
    expect(saveDocumentDraft).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Документ найден после проверки', status: 'info',
    }));
  });

  it('retires creation activity and late results when changing thread', async () => {
    let complete;
    const notify = jest.fn();
    createDocumentProject.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    const { result, rerender } = renderHook(({ threadId }) => useDocumentForge({
      threadId, notify, workspace: { state: 'ready', revision: 'r1',
        entries: [{ path: 'documents/current/document.toml' }] },
    }), { initialProps: { threadId: 'thread-1' } });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    let pending;
    act(() => { pending = result.current.createProject({
      path: 'documents/old-pending', initializeContent: true,
    }); });
    await waitFor(() => expect(createDocumentProject).toHaveBeenCalledTimes(1));
    expect(result.current.busy).toBe('create');
    rerender({ threadId: 'thread-2' });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    expect(result.current.busy).toBe('');
    await act(async () => { complete({ path: 'documents/old-pending',
      revision_changed: true, revision: 'r2' }); await pending; });
    expect(result.current.selectedProject).toBe(project.path);
    expect(saveDocumentDraft).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it('coalesces profile application before dispatch and clears its owned activity', async () => {
    applyDocumentProfile.mockResolvedValue({ path: project.path, outcome: 'updated' });
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    await act(async () => { await Promise.all([result.current.applyProfile(), result.current.applyProfile()]); });
    expect(applyDocumentProfile).toHaveBeenCalledTimes(1);
    expect(result.current.busy).toBe('');
  });

  it('retires profile activity and ignores its late reply after a thread change', async () => {
    let complete;
    const notify = jest.fn();
    applyDocumentProfile.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    const { result, rerender } = renderHook(({ threadId }) => useDocumentForge({
      threadId, notify, workspace: { state: 'ready', revision: 'r1',
        entries: [{ path: 'documents/current/document.toml' }] },
    }), { initialProps: { threadId: 'thread-1' } });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    const oldApply = result.current.applyProfile;
    let pending;
    act(() => { pending = oldApply(); });
    await waitFor(() => expect(applyDocumentProfile).toHaveBeenCalledTimes(1));
    expect(result.current.busy).toBe('profile');
    rerender({ threadId: 'thread-2' });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    expect(result.current.busy).toBe('');
    await act(async () => { complete({ path: 'documents/old-profile-copy' }); await pending; await oldApply(); });
    expect(result.current.selectedProject).toBe(project.path);
    expect(notify).not.toHaveBeenCalled();
    expect(applyDocumentProfile).toHaveBeenCalledTimes(1);
  });

  it('does not adopt a different profile after an unknown create result', async () => {
    const path = 'documents/unconfirmed';
    const notify = jest.fn();
    createDocumentProject.mockRejectedValueOnce(new Error('lost_reply'));
    const { result } = renderDocumentForge({ notify });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    getDocumentProject.mockResolvedValue({ ...project, path });
    await act(async () => { expect(await result.current.createProject({
      path, profileId: 'beamer_16_9', initializeContent: true,
    })).toBeNull(); });
    expect(result.current.selectedProject).toBe(project.path);
    expect(saveDocumentDraft).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it('distinguishes slow project discovery and a failed read from confirmed absence', async () => {
    let reject;
    getDocumentProject.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
    const { result } = renderDocumentForge();
    expect(result.current.project).toBeNull();
    expect(result.current.projectState).toBe('loading');
    await waitFor(() => expect(getDocumentProject).toHaveBeenCalledTimes(1));
    await act(async () => reject({ status: 503 }));
    expect(result.current.projectState).toBe('unavailable');
    await act(async () => result.current.loadProject());
    expect(result.current.projectState).toBe('ready');
    expect(result.current.project.path).toBe(project.path);
  });

  it('does not treat a malformed project response as permission to create', async () => {
    getDocumentProject.mockResolvedValueOnce({});
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.projectState).toBe('unavailable'));
    expect(result.current.project).toBeNull();
  });

  it('masks a previous thread project and ignores a retired response after switching projects', async () => {
    const settings = { threadId: 'thread-1', workspace: { state: 'ready', revision: 'r1',
      entries: [{ path: 'documents/current/document.toml' }, { path: 'documents/other/document.toml' }] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    let finishOld;
    getDocumentProject.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    rerender({ ...settings, threadId: 'thread-2' });
    expect(result.current.project).toBeNull();
    expect(result.current.projectState).toBe('loading');
    await waitFor(() => expect(finishOld).toBeDefined());
    getDocumentProject.mockResolvedValueOnce({ ...project, path: 'documents/other' });
    act(() => result.current.selectProject('documents/other'));
    await waitFor(() => expect(result.current.project?.path).toBe('documents/other'));
    await act(async () => finishOld(project));
    expect(result.current.project.path).toBe('documents/other');
    expect(result.current.projectState).toBe('ready');
  });

  it('reloads project and semantic draft when Workspace changes and when a run invalidates it', async () => {
    let version = 1;
    getDocumentProject.mockImplementation(async () => ({ ...project, authoring_state: 'ready',
      authoring_version: version, draft_digest: String(version).repeat(64) }));
    getDocumentAuthoringState.mockImplementation(async () => ({ authoring_version: version,
      draft: { title: `Version ${version}`, blocks: [] } }));
    const settings = { threadId: 'thread-1', workspace: { state: 'ready', revision: 'r1',
      entries: [{ path: 'documents/current/document.toml' }] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.authoring.value?.draft.title).toBe('Version 1'));
    version = 2;
    rerender({ ...settings, workspace: { ...settings.workspace, revision: 'r2' } });
    await waitFor(() => expect(result.current.authoring.value?.draft.title).toBe('Version 2'));
    version = 3;
    rerender({ ...settings, workspace: { ...settings.workspace, revision: 'r2' }, invalidationVersion: 1 });
    await waitFor(() => expect(result.current.authoring.value?.draft.title).toBe('Version 3'));
    expect(startDocumentBuild).not.toHaveBeenCalled();
  });

  it('keeps an explicitly selected profile instead of reloading the current one', async () => {
    const { result } = renderDocumentForge();

    await waitFor(() => expect(result.current.project?.path).toBe('documents/current'));

    act(() => result.current.setSelectedProfile('beamer_16_9'));

    expect(result.current.selectedProfile).toBe('beamer_16_9');
    expect(result.current.targetPath).toBe('documents/current-beamer_16_9');
    expect(getDocumentProject).toHaveBeenCalledTimes(1);
  });

  it('restarts a retired semantic read even when refreshed project stamps are unchanged', async () => {
    const semanticProject = { ...project, authoring_state: 'ready', authoring_version: 1,
      draft_digest: 'a'.repeat(64) };
    getDocumentProject.mockResolvedValue(semanticProject);
    let resolveRetired;
    getDocumentAuthoringState.mockImplementationOnce(() => new Promise((resolve) => { resolveRetired = resolve; }))
      .mockResolvedValue({ authoring_version: 1, draft: { title: 'Current draft', blocks: [] } });
    const settings = { threadId: 'thread-1', workspace: { state: 'ready', revision: 'r1',
      entries: [{ path: 'documents/current/document.toml' }] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(getDocumentAuthoringState).toHaveBeenCalledTimes(1));
    rerender({ ...settings, invalidationVersion: 1 });
    await waitFor(() => expect(getDocumentProject).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.authoring.value?.draft.title).toBe('Current draft'));
    expect(getDocumentAuthoringState).toHaveBeenCalledTimes(2);
    expect(getDocumentAuthoringState.mock.calls[0][2].signal.aborted).toBe(true);
    await act(async () => resolveRetired({ draft: { title: 'Retired draft', blocks: [] } }));
    expect(result.current.authoring.value?.draft.title).toBe('Current draft');
    expect(startDocumentBuild).not.toHaveBeenCalled();
  });

  it('coalesces the automatic semantic read with an explicit refresh for the same project generation', async () => {
    let resolve;
    const pending = new Promise((accept) => { resolve = accept; });
    getDocumentProject.mockResolvedValueOnce({ ...project, authoring_state: 'ready',
      authoring_version: 1, draft_digest: 'a'.repeat(64) });
    getDocumentAuthoringState.mockReturnValueOnce(pending);
    const { result } = renderDocumentForge();
    await waitFor(() => expect(getDocumentAuthoringState).toHaveBeenCalledTimes(1));
    let explicit;
    act(() => { explicit = result.current.loadAuthoring(project.path); });
    expect(getDocumentAuthoringState).toHaveBeenCalledTimes(1);
    const value = { authoring_version: 1, draft: { title: 'Обзор', blocks: [] } };
    await act(async () => { resolve(value); expect(await explicit).toBe(value); });
    expect(result.current.authoring.state).toBe('ready');
    expect(getDocumentAuthoringState.mock.calls[0][2].signal.aborted).toBe(false);
  });

  it('re-reads the clean authoring base when an asset changes revision but not draft version', async () => {
    let currentRevision = 'revision-1';
    getDocumentProject.mockImplementation(async () => ({ ...project, revision: currentRevision,
      authoring_state: 'ready', authoring_version: 1, draft_digest: 'a'.repeat(64) }));
    getDocumentAuthoringState.mockResolvedValue({ authoring_version: 1, draft: { title: 'Обзор', blocks: [] } });
    const view = renderHook(({ revision }) => useDocumentForge({ threadId: 'thread-1',
      workspace: { state: 'ready', revision, entries: [{ path: 'documents/current/document.toml' }] },
      library: { items: [] }, selectedPath: 'documents/current/main.tex' }), { initialProps: { revision: currentRevision } });
    await waitFor(() => expect(getDocumentAuthoringState).toHaveBeenCalledTimes(1));
    currentRevision = 'revision-2'; view.rerender({ revision: currentRevision });
    await waitFor(() => expect(getDocumentAuthoringState).toHaveBeenCalledTimes(2));
    expect(view.result.current.project.revision).toBe('revision-2');
    expect(view.result.current.authoring.value.authoring_version).toBe(1);
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
      publication_state: null,
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

  it('keeps tracking an admitted draft through lease invalidations and clears startup activity', async () => {
    let admit;
    startDocumentBuild.mockImplementationOnce(() => new Promise((resolve) => { admit = resolve; }));
    const ready = { build_id: 'draft-1', state: 'preview_ready', artifacts: [] };
    getDocumentBuild.mockResolvedValue(ready);
    const settings = { threadId: 'thread-1', workspace: { state: 'ready', revision: 'r1',
      entries: [{ path: 'documents/current/document.toml' }] }, refreshSnapshot: jest.fn() };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    let completion;
    act(() => { completion = result.current.buildProject(); });
    await waitFor(() => expect(admit).toBeDefined());
    rerender({ ...settings, invalidationVersion: 1 });
    await waitFor(() => expect(getDocumentProject).toHaveBeenCalledTimes(2));
    await act(async () => admit({ ...ready, state: 'building' }));
    await act(async () => { await completion; });
    expect(getDocumentBuild).toHaveBeenCalledTimes(1);
    expect(result.current.build).toEqual(ready);
    expect(result.current.busy).toBe('');
    expect(startDocumentBuild).toHaveBeenCalledTimes(1);
  });

  it('does not replace a running build with stale project facts or delay its status for lease release', async () => {
    let release;
    let finish;
    releaseWorkspaceLease.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    startDocumentBuild.mockResolvedValueOnce({ build_id: 'draft-2', state: 'building' });
    getDocumentBuild.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const settings = { threadId: 'thread-1', workspace: { state: 'ready', revision: 'r1',
      entries: [{ path: 'documents/current/document.toml' }] }, refreshSnapshot: jest.fn() };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    let completion;
    act(() => { completion = result.current.buildProject(); });
    await waitFor(() => expect(release).toBeDefined());
    expect(result.current.build.state).toBe('building');
    await act(async () => release({}));
    await waitFor(() => expect(finish).toBeDefined());
    rerender({ ...settings, invalidationVersion: 1 });
    await waitFor(() => expect(getDocumentProject).toHaveBeenCalledTimes(2));
    expect(result.current.build.state).toBe('building');
    await act(async () => finish({ build_id: 'draft-2', state: 'preview_ready', artifacts: [] }));
    await act(async () => { await completion; });
    expect(result.current.build.state).toBe('preview_ready');
    expect(result.current.busy).toBe('');
  });

  it('retires a delayed admission on thread change without leaking status or leaving startup busy', async () => {
    let admit;
    startDocumentBuild.mockImplementationOnce(() => new Promise((resolve) => { admit = resolve; }));
    const settings = { threadId: 'thread-1', workspace: { state: 'ready', revision: 'r1',
      entries: [{ path: 'documents/current/document.toml' }] } };
    const { result, rerender } = renderHook((props) => useDocumentForge(props), { initialProps: settings });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    let completion;
    act(() => { completion = result.current.buildProject(); });
    await waitFor(() => expect(admit).toBeDefined());
    rerender({ ...settings, threadId: 'thread-2' });
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    await act(async () => admit({ build_id: 'old-build', state: 'building' }));
    await act(async () => { await completion; });
    expect(result.current.build).toBeNull();
    expect(result.current.busy).toBe('');
    expect(getDocumentBuild).not.toHaveBeenCalled();
    expect(releaseWorkspaceLease).toHaveBeenCalledWith('thread-1', project.path, 7, expect.any(Object));
  });

  it('ignores a project build snapshot requested before a newer build completed', async () => {
    const { result } = renderDocumentForge();
    await waitFor(() => expect(result.current.projectState).toBe('ready'));
    let read;
    getDocumentProject.mockImplementationOnce(() => new Promise((resolve) => { read = resolve; }));
    let refresh;
    act(() => { refresh = result.current.loadProject(); });
    await waitFor(() => expect(read).toBeDefined());
    const ready = { build_id: 'new-draft', state: 'preview_ready', artifacts: [] };
    startDocumentBuild.mockResolvedValueOnce({ ...ready, state: 'building' });
    getDocumentBuild.mockResolvedValueOnce(ready);
    await act(async () => { await result.current.buildProject(); });
    expect(result.current.build).toEqual(ready);
    await act(async () => { read({ ...project, latest_build: null }); await refresh; });
    expect(result.current.build).toEqual(ready);
    expect(result.current.busy).toBe('');
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

  describe('publication ownership', () => {
    const finalBuild = {
      build_id: 'final-build', state: 'visual_pending', final: true,
      artifacts: [{ artifact_id: 'final-pdf', role: 'pdf' }],
    };
    const response = { publication_state: 'pending_delivery' };
    const notify = jest.fn();
    const refreshSnapshot = jest.fn();
    const renderPublication = () => renderHook(({ threadId }) => useDocumentForge({
      threadId,
      workspace: {
        state: 'ready', entries: [{ path: 'documents/current/document.toml' }],
      },
      library: { items: [] }, selectedPath: 'documents/current/main.tex',
      refreshSnapshot, notify,
    }), { initialProps: { threadId: 'thread-1' } });

    beforeEach(() => {
      getDocumentProject.mockResolvedValue({ ...project, latest_build: finalBuild });
      publishDocumentArtifact.mockResolvedValue(response);
      getDocumentBuild.mockResolvedValueOnce({ ...finalBuild, publication_state: null })
        .mockResolvedValue({ ...finalBuild, publication_state: 'delivered' });
      refreshSnapshot.mockResolvedValue(null);
    });

    it('does not misreport confirmed publication when independent refresh fails', async () => {
      refreshSnapshot.mockRejectedValue(new Error('PRIVATE-REFRESH'));
      const { result } = renderPublication();
      await waitFor(() => expect(result.current.build?.publication_state).toBeNull());
      let accepted;
      await act(async () => { accepted = await result.current.publish(); });
      expect(accepted).toEqual(response);
      expect(notify.mock.calls.some(([message]) => message.title === 'Финал пока не сохранён')).toBe(false);
    });

    it('rejects duplicate publish in the same event before a second dispatch', async () => {
      const { result } = renderPublication();
      await waitFor(() => expect(result.current.build?.publication_state).toBeNull());
      await act(async () => {
        await Promise.all([result.current.publish(), result.current.publish()]);
      });
      expect(publishDocumentArtifact).toHaveBeenCalledTimes(1);
    });

    it('rejects captured publication callback after changing thread', async () => {
      const { result, rerender } = renderPublication();
      await waitFor(() => expect(result.current.build?.publication_state).toBeNull());
      const captured = result.current.publish;
      rerender({ threadId: 'thread-2' });
      await act(async () => { await captured(); });
      expect(publishDocumentArtifact).not.toHaveBeenCalled();
    });
  });

  describe('PDF preview ownership', () => {
    let createUrl;
    let revokeUrl;
    const readyBuild = {
      build_id: 'preview-build',
      state: 'preview_ready',
      artifacts: [{ artifact_id: 'preview-pdf', role: 'pdf' }],
    };
    const renderPreview = () => renderHook(({ threadId }) => useDocumentForge({
      threadId,
      workspace: {
        state: 'ready',
        entries: [{ path: 'documents/current/document.toml' }],
      },
      library: { items: [] },
      selectedPath: 'documents/current/main.tex',
    }), { initialProps: { threadId: 'thread-1' } });

    beforeEach(() => {
      createUrl = URL.createObjectURL;
      revokeUrl = URL.revokeObjectURL;
      URL.createObjectURL = jest.fn(() => 'blob:owned-preview');
      URL.revokeObjectURL = jest.fn();
      getDocumentProject.mockResolvedValue({ ...project, latest_build: readyBuild });
    });

    afterEach(() => {
      cleanup();
      URL.createObjectURL = createUrl;
      URL.revokeObjectURL = revokeUrl;
    });

    it('ignores a late download after changing threads', async () => {
      let resolveDownload;
      downloadDocumentArtifact.mockImplementation(() => new Promise((resolve) => {
        resolveDownload = resolve;
      }));
      const { result, rerender } = renderPreview();
      await waitFor(() => expect(result.current.build?.build_id).toBe('preview-build'));
      let pending;
      act(() => { pending = result.current.openPreview(); });
      await waitFor(() => expect(downloadDocumentArtifact).toHaveBeenCalledTimes(1));
      rerender({ threadId: 'thread-2' });
      await act(async () => { resolveDownload(new Blob(['old'])); await pending; });
      expect(URL.createObjectURL).not.toHaveBeenCalled();
      expect(result.current.previewUrl).toBe('');
    });

    it('does not allocate an object URL after unmount', async () => {
      let resolveDownload;
      downloadDocumentArtifact.mockImplementation(() => new Promise((resolve) => {
        resolveDownload = resolve;
      }));
      const { result, unmount } = renderPreview();
      await waitFor(() => expect(result.current.build?.build_id).toBe('preview-build'));
      let pending;
      act(() => { pending = result.current.openPreview(); });
      await waitFor(() => expect(downloadDocumentArtifact).toHaveBeenCalledTimes(1));
      unmount();
      await act(async () => { resolveDownload(new Blob(['old'])); await pending; });
      expect(URL.createObjectURL).not.toHaveBeenCalled();
    });

    it('rejects duplicate preview activation before dispatch', async () => {
      downloadDocumentArtifact.mockResolvedValue(new Blob(['pdf']));
      const { result } = renderPreview();
      await waitFor(() => expect(result.current.build?.build_id).toBe('preview-build'));
      await act(async () => {
        await Promise.all([result.current.openPreview(), result.current.openPreview()]);
      });
      expect(downloadDocumentArtifact).toHaveBeenCalledTimes(1);
    });
  });
});
