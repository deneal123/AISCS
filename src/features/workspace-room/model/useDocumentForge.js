import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getWorkspaceActorSession } from './workspaceSession';
import { useDocumentPreview } from './useDocumentPreview';
import { useDocumentPublication } from './useDocumentPublication';
import { useWorkActionOwner } from './useWorkActionOwner';
import { initialDocumentDraft } from './initialDocumentDraft';

const BUILD_WAIT_STATES = new Set(['preview_ready', 'visual_pending', 'ready', 'failed', 'cancelled']);
const PROJECT_MANIFEST = /(^|\/)document\.toml$/i;

const findProject = (entries = [], selectedPath = '') => {
  const selected = String(selectedPath || '');
  const selectedMarker = selected.includes('/')
    ? `${selected.slice(0, selected.lastIndexOf('/'))}/document.toml`
    : 'document.toml';
  const paths = entries.map((item) => String(item?.path || item?.name || ''));
  const marker = paths.includes(selectedMarker)
    ? selectedMarker
    : paths.find((path) => PROJECT_MANIFEST.test(path));
  return marker ? marker.replace(/\/?document\.toml$/i, '') : '';
};

export function useDocumentForge({
  threadId,
  invalidationVersion = 0,
  workspace,
  library,
  selectedPath,
  refreshSnapshot,
  notify,
  onOpenSource,
  active = true,
}) {
  const [profiles, setProfiles] = useState([]);
  const [profilesState, setProfilesState] = useState('idle');
  const [selectedProfile, setSelectedProfile] = useState('generic_document');
  const [selectedMode, setSelectedMode] = useState('draft');
  const [selectedLocale, setSelectedLocale] = useState('ru-RU');
  const [project, setProject] = useState(null);
  const projectOwner = useRef('');
  const [projectRead, setProjectRead] = useState({ threadId: '', path: '', state: 'idle' });
  const projectPathRef = useRef('');
  projectPathRef.current = project?.path || '';
  const [selectedProject, setSelectedProject] = useState('');
  const [authoring, setAuthoring] = useState({ state: 'idle', value: null });
  const [build, setBuild] = useState(null);
  const [targetPath, setTargetPath] = useState('');
  const [vendorTargetPath, setVendorTargetPath] = useState('');
  const [selectedVendorFile, setSelectedVendorFile] = useState('');
  const [selectedVendorPackage, setSelectedVendorPackage] = useState('');
  const [busy, setBusy] = useState('');
  const { busy: projectMutationBusy, begin: beginProjectMutation, owns: ownsProjectMutation, finish: finishProjectMutation } = useWorkActionOwner({ threadId, active });
  const { previewUrl, previewError, previewBusy, openPreview } = useDocumentPreview({
    threadId, build, active, projectPath: project?.path || '',
  });
  const {
    publish, checkPublication, publicationError, publicationChecking, publicationBusy,
  } = useDocumentPublication({
    threadId, build, setBuild, refreshSnapshot, notify, active,
    blocked: Boolean(busy) || workspace?.state !== 'ready',
  });
  const generation = useRef(0);
  const pollController = useRef(null);
  const buildEpoch = useRef(0);
  const profilesController = useRef(null);
  const profilesOwner = useRef('');
  const projectController = useRef(null);
  const authoringController = useRef(null);
  const pendingAuthoring = useRef(null);
  const observedProject = useRef(null);
  const actorSession = getWorkspaceActorSession();
  const detectedPath = useMemo(
    () => selectedProject || findProject(workspace?.entries, selectedPath),
    [selectedProject, selectedPath, workspace?.entries],
  );
  useEffect(() => { setSelectedProject(''); }, [threadId]);
  const vendorFiles = useMemo(
    () => (library?.items || []).filter((item) => (
      item?.availability === 'ready'
      && String(item?.name || '').toLowerCase().endsWith('.zip')
    )),
    [library?.items],
  );
  const vendorProfiles = useMemo(
    () => (project?.vendor_overlays || []).filter((item) => item?.profile_available),
    [project?.vendor_overlays],
  );

  useEffect(() => {
    setSelectedVendorFile((current) => (
      vendorFiles.some((item) => item.file_id === current)
        ? current
        : String(vendorFiles[0]?.file_id || '')
    ));
  }, [threadId, vendorFiles]);

  useEffect(() => {
    setSelectedVendorPackage((current) => (
      vendorProfiles.some((item) => item.package_id === current)
        ? current
        : String(vendorProfiles[0]?.package_id || '')
    ));
  }, [threadId, vendorProfiles]);

  const stopPolling = useCallback(() => {
    if (pollController.current) setBusy((value) => (['build', 'final'].includes(value) ? '' : value));
    pollController.current?.abort();
    pollController.current = null;
  }, []);

  useEffect(() => () => {
    generation.current += 1;
    stopPolling();
    profilesController.current?.abort();
    projectController.current?.abort();
    authoringController.current?.abort();
  }, [stopPolling]);

  const loadProfiles = useCallback(async () => {
    if (!threadId) return [];
    profilesController.current?.abort();
    profilesOwner.current = '';
    const controller = new AbortController();
    profilesController.current = controller;
    setProfilesState('loading');
    try {
      const { getDocumentProfiles } = await import('@api/chat');
      const result = await getDocumentProfiles(threadId, { signal: controller.signal });
      if (controller.signal.aborted) return [];
      const next = Array.isArray(result?.profiles) ? result.profiles : [];
      if (!next.length) throw new Error('document_profiles_unavailable');
      profilesOwner.current = threadId;
      setProfiles(next);
      setProfilesState('ready');
      setSelectedProfile((current) => (
        next.length && !next.some((item) => item.profile_id === current)
          ? next[0].profile_id
          : current
      ));
      return next;
    } catch {
      if (!controller.signal.aborted) setProfilesState('unavailable');
      return [];
    } finally {
      if (profilesController.current === controller) profilesController.current = null;
    }
  }, [threadId]);

  const loadProject = useCallback(async (path = detectedPath) => {
    const buildInProgress = Boolean(pollController.current);
    const expectedBuildEpoch = buildEpoch.current;
    projectController.current?.abort();
    const current = ++generation.current;
    if (projectOwner.current !== threadId || path !== projectPathRef.current) setAuthoring({ state: 'idle', value: null });
    if (!threadId || !path) {
      setProject(null);
      projectOwner.current = '';
      setBuild(null);
      setAuthoring({ state: 'idle', value: null });
      setProjectRead({ threadId, path: '', state: 'absent' });
      return null;
    }
    const controller = new AbortController();
    projectController.current = controller;
    setProjectRead({ threadId, path, state: 'loading' });
    try {
      const { getDocumentProject } = await import('@api/chat');
      const result = await getDocumentProject(threadId, path, { signal: controller.signal });
      if (controller.signal.aborted || current !== generation.current) return null;
      if (result?.path !== path) throw new Error('invalid_document_project');
      setProject(result);
      projectOwner.current = threadId;
      // Background discovery cannot retire the confirmed editor identity.
      setSelectedProject(current => current || path);
      setProjectRead({ threadId, path, state: 'ready', generation: current });
      // Lease events refresh project facts while a build owns its own status.
      // A delayed project read must not replace that status, even after it finishes.
      if (!buildInProgress && !pollController.current && expectedBuildEpoch === buildEpoch.current) {
        setBuild(result?.latest_build || null);
      }
      setSelectedProfile(result?.profile?.profile_id || 'generic_document');
      setSelectedMode(result?.mode || 'draft');
      setSelectedLocale(result?.locale || result?.profile?.locale || 'ru-RU');
      return result;
    } catch {
      if (!controller.signal.aborted && current === generation.current) {
        setProjectRead({ threadId, path, state: 'unavailable' });
      }
      return null;
    } finally {
      if (projectController.current === controller) projectController.current = null;
    }
  }, [detectedPath, threadId]);

  const loadAuthoring = useCallback(async (path = project?.path || detectedPath) => {
    if (!threadId || !path) {
      setAuthoring({ state: 'idle', value: null });
      return null;
    }
    const current = generation.current;
    const key = JSON.stringify([threadId, path, current]);
    const pending = pendingAuthoring.current;
    // The project effect and explicit post-save refresh share one exact read.
    // A different generation/path still aborts and retires the previous response.
    if (pending?.key === key && !pending.controller.signal.aborted) return pending.promise;
    authoringController.current?.abort();
    const controller = new AbortController();
    authoringController.current = controller;
    const request = { key, controller, promise: null };
    setAuthoring((previous) => ({
      state: previous.value ? 'stale' : 'loading',
      value: previous.value,
    }));
    request.promise = (async () => {
      try {
        const { getDocumentAuthoringState } = await import('@api/chat');
        if (controller.signal.aborted || current !== generation.current) return null;
        const result = await getDocumentAuthoringState(threadId, path, { signal: controller.signal });
        if (controller.signal.aborted || current !== generation.current) return null;
        setAuthoring({ state: 'ready', value: result });
        return result;
      } catch (error) {
        if (controller.signal.aborted || current !== generation.current) return null;
        const status = Number(error?.status || error?.response?.status || 0);
        setAuthoring((previous) => ({
          state: status === 404 ? 'absent' : 'unavailable',
          value: status === 404 ? null : previous.value,
        }));
        return null;
      } finally {
        if (authoringController.current === controller) authoringController.current = null;
        if (pendingAuthoring.current === request) pendingAuthoring.current = null;
      }
    })();
    pendingAuthoring.current = request;
    return request.promise;
  }, [detectedPath, project?.path, threadId]);

  useEffect(() => {
    if (!project?.path) {
      setTargetPath('');
      return;
    }
    if (project?.profile?.profile_id === selectedProfile) {
      setTargetPath(project.path);
      return;
    }
    const safeProfile = String(selectedProfile || 'profile')
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'profile';
    setTargetPath(`${project.path}-${safeProfile}`);
  }, [project?.path, project?.profile?.profile_id, selectedProfile]);

  useEffect(() => {
    if (!project?.path || !selectedVendorPackage) {
      setVendorTargetPath('');
      return;
    }
    const safePackage = String(selectedVendorPackage)
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'vendor';
    setVendorTargetPath(`${project.path}-${safePackage}`);
  }, [project?.path, selectedVendorPackage]);

  useEffect(() => {
    if (!active || !threadId) return undefined;
    if (profilesOwner.current !== threadId) {
      setProfiles([]);
      void loadProfiles();
    }
    return () => profilesController.current?.abort();
  }, [active, threadId, loadProfiles]);

  useEffect(() => {
    if (workspace?.state !== 'ready') return undefined;
    loadProject();
    return () => {
      generation.current += 1;
      stopPolling();
      projectController.current?.abort();
      authoringController.current?.abort();
    };
  }, [loadProject, stopPolling, workspace?.state]);

  useEffect(() => {
    const key = `${threadId}/${detectedPath}`;
    const stamp = `${workspace?.revision}/${invalidationVersion}`;
    const previous = observedProject.current;
    observedProject.current = { key, stamp };
    // Read refreshed facts without cancelling an independently owned compilation.
    if (workspace?.state === 'ready' && detectedPath && previous?.key === key && previous.stamp !== stamp) {
      void loadProject(detectedPath);
    }
  }, [detectedPath, invalidationVersion, loadProject, threadId, workspace?.revision, workspace?.state]);

  useEffect(() => {
    if (projectRead.state !== 'ready') return;
    if (project?.path && project.authoring_state === 'ready') {
      void loadAuthoring(project.path);
    } else if (project?.path) {
      setAuthoring({ state: 'absent', value: null });
    }
    // Every accepted project read owns a fresh semantic read. Revision/version
    // can stay unchanged while an earlier pending read is retired by generation.
  }, [loadAuthoring, projectRead.generation, projectRead.state, project?.authoring_state, project?.authoring_version, project?.draft_digest, project?.path, project?.revision]);

  const withLease = useCallback(async (path, operation) => {
    const api = await import('@api/chat');
    const lease = await api.acquireWorkspaceLease(threadId, path, { actorSession });
    try {
      return await operation(api, Number(lease?.fence || 0));
    } finally {
      if (lease?.fence) {
        try {
          await api.releaseWorkspaceLease(threadId, path, Number(lease.fence), {
            actorSession,
          });
        } catch {
          // Lease TTL bounds best-effort release after a completed mutation.
        }
      }
    }
  }, [actorSession, threadId]);

  const createProject = useCallback(async (selection = {}, { prepareWorkspace } = {}) => {
    if (!threadId || busy || projectMutationBusy) return null;
    if (workspace?.state !== 'ready' && !prepareWorkspace) return null;
    const ticket = beginProjectMutation(threadId, 'create');
    if (!ticket) return null;
    const path = selection.path || `documents/document-${Date.now().toString(36)}`;
    let sourceOnly = false;
    try {
      // Only an explicit new-document submission may allocate after expiry.
      // Use the acknowledged revision, not the stale render captured before activation.
      const targetWorkspace = workspace?.state === 'ready'
        ? { state: workspace.state, revision: workspace.revision } : await prepareWorkspace();
      if (!ownsProjectMutation(ticket) || targetWorkspace?.state !== 'ready' || !targetWorkspace.revision) return null;
      const result = await withLease(path, async (api, fence) => {
        if (!ownsProjectMutation(ticket)) return null;
        const profileId = selection.profileId || selectedProfile;
        const created = await api.createDocumentProject(threadId, {
          path, profile_id: profileId, mode: selection.mode || selectedMode,
          locale: selection.locale || selectedLocale, expected_revision: targetWorkspace.revision, fence,
        }, { actorSession });
        // Initialize only this fresh acknowledged scaffold. Never retry a source
        // write after a lost ACK or replace the previously open document.
        if (selection.initializeContent === true && ownsProjectMutation(ticket)
          && created?.path === path && created.revision_changed === true && created.revision) {
          try {
            await api.saveDocumentDraft(threadId, {
              path, draft: initialDocumentDraft(/^beamer(?:_|$)/.test(profileId)),
              expected_revision: created.revision, authoring_version: 0, draft_digest: null, fence,
            }, { actorSession });
          } catch {
            sourceOnly = true;
          }
        }
        return created;
      });
      if (!ownsProjectMutation(ticket) || !result) return null;
      await refreshSnapshot({ background: true });
      if (!ownsProjectMutation(ticket)) return null;
      await loadProject(path);
      if (!ownsProjectMutation(ticket)) return null;
      setSelectedProject(path);
      notify?.(sourceOnly ? {
        title: 'Проект создан, доступны исходники',
        description: 'Визуальный редактор не подготовлен. Откройте вкладку LaTeX.',
        status: 'warning', duration: 4500,
      } : { title: 'Проект документа создан', status: 'success', duration: 2200 });
      return result;
    } catch {
      if (!ownsProjectMutation(ticket)) return null;
      await refreshSnapshot({ background: true });
      if (!ownsProjectMutation(ticket)) return null;
      // A lost create reply is not permission to repeat scaffold/source writes.
      // Only the modal's stable destination can be reconciled by passive reads.
      if (selection.initializeContent === true && selection.path) {
        try {
          const { getDocumentProject } = await import('@api/chat');
          if (!ownsProjectMutation(ticket)) return null;
          const observed = await getDocumentProject(threadId, path);
          if (!ownsProjectMutation(ticket)) return null;
          if (observed?.path === path
            && observed.profile?.profile_id === (selection.profileId || selectedProfile)
            && observed.mode === (selection.mode || selectedMode)
            && observed.locale === (selection.locale || selectedLocale)) {
            const loaded = await loadProject(path);
            if (!ownsProjectMutation(ticket)) return null;
            if (loaded) {
              setSelectedProject(path);
              notify?.({ title: 'Документ найден после проверки',
                description: 'Открыт созданный проект. Повторная запись исходников не выполнялась.',
                status: 'info', duration: 3500 });
              return loaded;
            }
          }
        } catch {
          // Keep the same destination and the existing project on unknown reads.
        }
      }
      if (!ownsProjectMutation(ticket)) return null;
      // The modal owns its recoverable inline error; do not stack a second
      // notification or claim that an unacknowledged creation did not happen.
      if (selection.initializeContent !== true) notify?.({
        title: 'Создание документа не подтверждено',
        description: 'Проверьте список проектов перед повторной попыткой.',
        status: 'warning', duration: 3200,
      });
      return null;
    } finally {
      finishProjectMutation(ticket);
    }
  }, [
    beginProjectMutation,
    ownsProjectMutation,
    finishProjectMutation,
    busy,
    projectMutationBusy,
    actorSession,
    loadProject,
    notify,
    refreshSnapshot,
    selectedProfile,
    selectedMode,
    selectedLocale,
    threadId,
    withLease,
    workspace?.revision,
    workspace?.state,
  ]);

  const applyProfile = useCallback(async () => {
    if (busy || projectMutationBusy || !project?.path || !workspace?.revision) return null;
    // Share the project mutation owner with creation: no double dispatch or
    // stale callback may apply formatting in another thread.
    const ticket = beginProjectMutation(threadId, 'profile');
    if (!ticket) return null;
    try {
      const result = await withLease(project.path, (api, fence) => ownsProjectMutation(ticket) ? api.applyDocumentProfile(
        threadId,
        {
          path: project.path,
          target_path: targetPath || project.path,
          profile_id: selectedProfile,
          mode: selectedMode,
          locale: selectedLocale,
          expected_revision: workspace.revision,
          fence,
        },
        { actorSession },
      ) : null);
      if (!ownsProjectMutation(ticket) || !result) return null;
      await refreshSnapshot({ background: true });
      if (!ownsProjectMutation(ticket)) return null;
      await loadProject(result?.path || project.path);
      if (!ownsProjectMutation(ticket)) return null;
      setSelectedProject(result?.path || project.path);
      notify?.({
        title: result?.outcome === 'cloned' ? 'Создан проект с новым профилем' : 'Профиль обновлён',
        description: result?.content_status === 'content_migration_required'
          ? 'Исходный текст сохранён для ручного переноса; исходный проект не изменён.'
          : undefined,
        status: result?.content_status === 'content_migration_required' ? 'warning' : 'success',
        duration: 3200,
      });
      return result;
    } catch {
      if (!ownsProjectMutation(ticket)) return null;
      notify?.({ title: 'Применение настроек не подтверждено',
        description: 'Проверьте текущие настройки перед повторной попыткой.',
        status: 'warning', duration: 3500 });
      await refreshSnapshot({ background: true });
      return null;
    } finally {
      finishProjectMutation(ticket);
    }
  }, [
    beginProjectMutation,
    ownsProjectMutation,
    finishProjectMutation,
    busy,
    projectMutationBusy,
    actorSession,
    loadProject,
    notify,
    project?.path,
    refreshSnapshot,
    selectedProfile,
    selectedMode,
    selectedLocale,
    targetPath,
    threadId,
    withLease,
    workspace?.revision,
  ]);

  const applyVendorOverlay = useCallback(async () => {
    if (!project?.path || !workspace?.revision || !selectedVendorFile) return null;
    setBusy('vendor');
    try {
      const result = await withLease(project.path, (api, fence) => (
        api.applyDocumentVendorOverlay(
          threadId,
          selectedVendorFile,
          {
            path: project.path,
            expected_revision: workspace.revision,
            fence,
          },
          { actorSession },
        )
      ));
      await refreshSnapshot({ background: true });
      await loadProject(project.path);
      notify?.({
        title: result?.outcome === 'kept'
          ? 'Vendor-пакет уже подключён'
          : 'Vendor-пакет добавлен в проект',
        description: 'Пакет действует только внутри этого проекта и не меняет среду сборки.',
        status: result?.outcome === 'kept' ? 'info' : 'success',
        duration: 3200,
      });
      return result;
    } catch {
      notify?.({
        title: 'Vendor-пакет не добавлен',
        description: 'Архив отклонён или рабочее место изменилось. Исходный проект сохранён.',
        status: 'warning',
        duration: 3600,
      });
      await refreshSnapshot({ background: true });
      return null;
    } finally {
      setBusy('');
    }
  }, [
    actorSession,
    loadProject,
    notify,
    project?.path,
    refreshSnapshot,
    selectedVendorFile,
    threadId,
    withLease,
    workspace?.revision,
  ]);

  const activateVendorProfile = useCallback(async () => {
    if (
      !project?.path
      || !workspace?.revision
      || !selectedVendorPackage
      || !String(vendorTargetPath || '').trim()
    ) return null;
    setBusy('vendor-profile');
    try {
      const result = await withLease(project.path, (api, fence) => (
        api.activateDocumentVendorProfile(
          threadId,
          selectedVendorPackage,
          {
            path: project.path,
            target_path: vendorTargetPath,
            expected_revision: workspace.revision,
            fence,
          },
          { actorSession },
        )
      ));
      await refreshSnapshot({ background: true });
      await loadProject(result?.path || vendorTargetPath);
      notify?.({
        title: 'Создан проект с форматом издателя',
        description: result?.content_status === 'content_migration_required'
          ? 'Исходный текст сохранён для ручного переноса; исходный проект не изменён.'
          : 'Формат прошёл изолированную пробную сборку. Исходный проект сохранён.',
        status: result?.content_status === 'content_migration_required' ? 'warning' : 'success',
        duration: 3600,
      });
      return result;
    } catch {
      notify?.({
        title: 'Формат издателя не активирован',
        description: 'Пробная сборка не прошла или проект изменился. Исходник не затронут.',
        status: 'warning',
        duration: 3600,
      });
      await refreshSnapshot({ background: true });
      return null;
    } finally {
      setBusy('');
    }
  }, [
    actorSession,
    loadProject,
    notify,
    project?.path,
    refreshSnapshot,
    selectedVendorPackage,
    threadId,
    vendorTargetPath,
    withLease,
    workspace?.revision,
  ]);

  const pollBuild = useCallback(async (buildId, signal) => {
    const { getDocumentBuild } = await import('@api/chat');
    for (let attempt = 0; attempt < 300; attempt += 1) {
      if (signal.aborted) return null;
      const status = await getDocumentBuild(threadId, buildId, { signal });
      if (signal.aborted) return null;
      setBuild(status);
      if (BUILD_WAIT_STATES.has(status?.state)) return status;
      await new Promise((resolve) => {
        const timer = window.setTimeout(resolve, 1000);
        signal.addEventListener('abort', () => {
          window.clearTimeout(timer);
          resolve();
        }, { once: true });
      });
    }
    return null;
  }, [threadId]);

  const buildProject = useCallback(async (final = false) => {
    if (!project?.path || !workspace?.revision) return null;
    buildEpoch.current += 1;
    stopPolling();
    setBusy(final ? 'final' : 'build');
    const controller = new AbortController();
    pollController.current = controller;
    try {
      const started = await withLease(project.path, async (api, fence) => {
        const accepted = await api.startDocumentBuild(threadId, {
          path: project.path,
          expected_revision: workspace.revision,
          fence,
          final,
        }, { actorSession });
        if (!controller.signal.aborted) setBuild(accepted);
        return accepted;
      });
      if (controller.signal.aborted) return null;
      const result = await pollBuild(started.build_id, controller.signal);
      if (result?.state === 'ready') {
        notify?.({ title: 'PDF прошёл техническую проверку', status: 'success', duration: 2600 });
        await refreshSnapshot({ background: true });
      } else if (result?.state === 'preview_ready') {
        notify?.({ title: 'Черновик PDF собран', status: 'success', duration: 2400 });
      } else if (result?.state === 'visual_pending') {
        notify?.({
          title: 'Компиляция завершена',
          description: 'Для финала нужна визуальная проверка перед сохранением в Библиотеку.',
          status: 'info',
          duration: 3600,
        });
      }
      return result;
    } catch {
      if (controller.signal.aborted) return null;
      notify?.({
        title: 'Сборка документа не завершена',
        description: 'Исходники и несохранённый текст не перезаписаны.',
        status: 'warning',
        duration: 3400,
      });
      return null;
    } finally {
      if (pollController.current === controller) {
        pollController.current = null;
        setBusy('');
      }
    }
  }, [
    actorSession,
    notify,
    pollBuild,
    project?.path,
    refreshSnapshot,
    threadId,
    stopPolling,
    withLease,
    workspace?.revision,
  ]);

  const cancelBuild = useCallback(async () => {
    if (!build?.build_id || !project?.path) return;
    buildEpoch.current += 1;
    generation.current += 1;
    stopPolling();
    setBusy('cancel');
    try {
      const result = await withLease(project.path, (api, fence) => api.cancelDocumentBuild(
        threadId, build.build_id, fence, { actorSession },
      ));
      setBuild(result);
    } finally {
      setBusy('');
    }
  }, [actorSession, build?.build_id, project?.path, stopPolling, threadId, withLease]);

  const openDiagnostic = useCallback(async (diagnostic) => {
    if (!project?.path || !diagnostic?.path || !onOpenSource) return false;
    const relative = String(diagnostic.path).replace(/^\/+/, '');
    return onOpenSource(`${project.path}/${relative}`, { line: diagnostic.line || null });
  }, [onOpenSource, project?.path]);

  const visibleProject = projectOwner.current === threadId && project?.path === detectedPath ? project : null;
  const projectState = workspace?.state !== 'ready' ? 'idle' : !detectedPath ? 'absent'
    : projectRead.threadId !== threadId || projectRead.path !== detectedPath ? 'loading'
      : projectRead.state === 'loading' && visibleProject ? 'refreshing' : projectRead.state;

  return {
    profiles,
    profilesState,
    loadProfiles,
    selectedProfile,
    setSelectedProfile,
    selectedMode,
    setSelectedMode,
    selectedLocale,
    setSelectedLocale,
    targetPath,
    setTargetPath,
    vendorFiles,
    selectedVendorFile,
    setSelectedVendorFile,
    vendorProfiles,
    selectedVendorPackage,
    setSelectedVendorPackage,
    vendorTargetPath,
    setVendorTargetPath,
    project: visibleProject,
    projectState,
    selectedProject,
    selectProject: setSelectedProject,
    authoring: visibleProject ? authoring : { state: 'idle', value: null },
    build: visibleProject ? build : null,
    busy: busy || projectMutationBusy || (publicationBusy ? 'publish' : ''),
    publicationError,
    publicationChecking,
    checkPublication,
    previewUrl: visibleProject ? previewUrl : '',
    previewError,
    previewBusy,
    createProject,
    applyProfile,
    applyVendorOverlay,
    activateVendorProfile,
    buildProject,
    cancelBuild,
    openPreview,
    openDiagnostic,
    loadAuthoring,
    loadProject,
    publish,
  };
}
