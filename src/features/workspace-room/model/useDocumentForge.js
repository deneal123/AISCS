import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getWorkspaceActorSession } from './workspaceSession';

const BUILD_WAIT_STATES = new Set(['preview_ready', 'visual_pending', 'ready', 'failed', 'cancelled']);
const PUBLICATION_WAIT_STATES = new Set(['delivered', 'terminal']);
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
  workspace,
  library,
  selectedPath,
  refreshSnapshot,
  notify,
  onOpenSource,
}) {
  const [profiles, setProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState('generic_document');
  const [selectedMode, setSelectedMode] = useState('draft');
  const [selectedLocale, setSelectedLocale] = useState('ru-RU');
  const [project, setProject] = useState(null);
  const [authoring, setAuthoring] = useState({ state: 'idle', value: null });
  const [build, setBuild] = useState(null);
  const [targetPath, setTargetPath] = useState('');
  const [vendorTargetPath, setVendorTargetPath] = useState('');
  const [selectedVendorFile, setSelectedVendorFile] = useState('');
  const [selectedVendorPackage, setSelectedVendorPackage] = useState('');
  const [busy, setBusy] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');
  const generation = useRef(0);
  const pollController = useRef(null);
  const profilesController = useRef(null);
  const projectController = useRef(null);
  const authoringController = useRef(null);
  const actorSession = getWorkspaceActorSession();
  const detectedPath = useMemo(
    () => findProject(workspace?.entries, selectedPath),
    [selectedPath, workspace?.entries],
  );
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

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const loadProfiles = useCallback(async () => {
    if (!threadId) return [];
    profilesController.current?.abort();
    const controller = new AbortController();
    profilesController.current = controller;
    try {
      const { getDocumentProfiles } = await import('@api/chat');
      const result = await getDocumentProfiles(threadId, { signal: controller.signal });
      if (controller.signal.aborted) return [];
      const next = Array.isArray(result?.profiles) ? result.profiles : [];
      setProfiles(next);
      setSelectedProfile((current) => (
        next.length && !next.some((item) => item.profile_id === current)
          ? next[0].profile_id
          : current
      ));
      return next;
    } catch {
      return [];
    } finally {
      if (profilesController.current === controller) profilesController.current = null;
    }
  }, [threadId]);

  const loadProject = useCallback(async (path = detectedPath) => {
    if (!threadId || !path) {
      setProject(null);
      setBuild(null);
      setAuthoring({ state: 'idle', value: null });
      return null;
    }
    projectController.current?.abort();
    const controller = new AbortController();
    projectController.current = controller;
    const current = ++generation.current;
    try {
      const { getDocumentProject } = await import('@api/chat');
      const result = await getDocumentProject(threadId, path, { signal: controller.signal });
      if (current !== generation.current) return null;
      setProject(result);
      setBuild(result?.latest_build || null);
      setSelectedProfile(result?.profile?.profile_id || 'generic_document');
      setSelectedMode(result?.mode || 'draft');
      setSelectedLocale(result?.locale || result?.profile?.locale || 'ru-RU');
      return result;
    } catch {
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
    authoringController.current?.abort();
    const controller = new AbortController();
    authoringController.current = controller;
    const current = generation.current;
    setAuthoring((previous) => ({
      state: previous.value ? 'stale' : 'loading',
      value: previous.value,
    }));
    try {
      const { getDocumentAuthoringState } = await import('@api/chat');
      const result = await getDocumentAuthoringState(threadId, path, {
        signal: controller.signal,
      });
      if (controller.signal.aborted || current !== generation.current) return null;
      setAuthoring({ state: 'ready', value: result });
      return result;
    } catch (error) {
      if (controller.signal.aborted || current !== generation.current) return null;
      const status = Number(error?.response?.status || 0);
      setAuthoring((previous) => ({
        state: status === 404 ? 'absent' : 'unavailable',
        value: status === 404 ? null : previous.value,
      }));
      return null;
    } finally {
      if (authoringController.current === controller) authoringController.current = null;
    }
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
    if (workspace?.state !== 'ready') return undefined;
    loadProfiles();
    loadProject();
    return () => {
      generation.current += 1;
      stopPolling();
      profilesController.current?.abort();
      projectController.current?.abort();
      authoringController.current?.abort();
    };
  }, [loadProfiles, loadProject, stopPolling, workspace?.state]);

  useEffect(() => {
    if (project?.path && project.authoring_state === 'ready') {
      void loadAuthoring(project.path);
    } else if (project?.path) {
      setAuthoring({ state: 'absent', value: null });
    }
  }, [loadAuthoring, project?.authoring_state, project?.path]);

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

  const createProject = useCallback(async () => {
    if (!threadId || workspace?.state !== 'ready' || !workspace?.revision) return null;
    setBusy('create');
    const path = `documents/document-${Date.now().toString(36)}`;
    try {
      const result = await withLease(path, (api, fence) => api.createDocumentProject(
        threadId,
        {
          path,
          profile_id: selectedProfile,
          mode: selectedMode,
          locale: selectedLocale,
          expected_revision: workspace.revision,
          fence,
        },
        { actorSession },
      ));
      await refreshSnapshot({ background: true });
      await loadProject(path);
      notify?.({ title: 'Проект документа создан', status: 'success', duration: 2200 });
      return result;
    } catch {
      notify?.({
        title: 'Не удалось создать проект документа',
        description: 'Рабочее место перечитано без потери правок.',
        status: 'warning',
        duration: 3200,
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
    if (!project?.path || !workspace?.revision) return null;
    setBusy('profile');
    try {
      const result = await withLease(project.path, (api, fence) => api.applyDocumentProfile(
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
      ));
      await refreshSnapshot({ background: true });
      await loadProject(result?.path || project.path);
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
      notify?.({ title: 'Профиль не применён', status: 'warning', duration: 3000 });
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

  const pollBuild = useCallback(async (buildId, currentGeneration, signal) => {
    const { getDocumentBuild } = await import('@api/chat');
    for (let attempt = 0; attempt < 300; attempt += 1) {
      if (signal.aborted || currentGeneration !== generation.current) return null;
      const status = await getDocumentBuild(threadId, buildId, { signal });
      if (currentGeneration !== generation.current) return null;
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

  const pollPublication = useCallback(async (buildId, currentGeneration, signal) => {
    const { getDocumentBuild } = await import('@api/chat');
    for (let attempt = 0; attempt < 300; attempt += 1) {
      if (signal.aborted || currentGeneration !== generation.current) return null;
      const status = await getDocumentBuild(threadId, buildId, { signal });
      if (signal.aborted || currentGeneration !== generation.current) return null;
      setBuild(status);
      if (PUBLICATION_WAIT_STATES.has(status?.publication_state)) return status;
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
    setBusy(final ? 'final' : 'build');
    stopPolling();
    const controller = new AbortController();
    pollController.current = controller;
    const current = ++generation.current;
    try {
      const started = await withLease(project.path, (api, fence) => api.startDocumentBuild(
        threadId,
        {
          path: project.path,
          expected_revision: workspace.revision,
          fence,
          final,
        },
        { actorSession },
      ));
      setBuild(started);
      const result = await pollBuild(started.build_id, current, controller.signal);
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
      if (pollController.current === controller) pollController.current = null;
      if (current === generation.current) setBusy('');
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

  const openPreview = useCallback(async () => {
    const artifact = build?.artifacts?.find((item) => item.role === 'pdf');
    if (!artifact) return;
    const { downloadDocumentArtifact } = await import('@api/chat');
    const blob = await downloadDocumentArtifact(threadId, build.build_id, artifact.artifact_id);
    const next = URL.createObjectURL(blob);
    setPreviewUrl((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return next;
    });
  }, [build, threadId]);

  const publish = useCallback(async () => {
    const artifact = build?.artifacts?.find((item) => item.role === 'pdf');
    if (!artifact) return null;
    setBusy('publish');
    try {
      const { publishDocumentArtifact } = await import('@api/chat');
      const result = await publishDocumentArtifact(
        threadId, build.build_id, artifact.artifact_id,
      );
      setBuild((current) => ({
        ...(current || {}),
        publication_state: result?.publication_state || 'pending_delivery',
      }));
      notify?.({
        title: result?.file_id ? 'Финальный PDF уже в Библиотеке' : 'Сохранение поставлено в очередь',
        description: result?.file_id
          ? undefined
          : 'Проверка и доставка продолжатся в фоне; страницу можно обновить.',
        status: result?.file_id ? 'success' : 'info',
        duration: 3400,
      });
      await refreshSnapshot({ background: true });
      stopPolling();
      const controller = new AbortController();
      pollController.current = controller;
      const current = ++generation.current;
      void pollPublication(build.build_id, current, controller.signal).then((status) => {
        if (status?.publication_state === 'delivered') {
          notify?.({ title: 'Финальный PDF сохранён в Библиотеке', status: 'success' });
          void refreshSnapshot({ background: true });
        }
      });
      return result;
    } catch {
      notify?.({
        title: 'Финал пока не сохранён',
        description: 'Исходники и PDF не удалены. Повторите сохранение после восстановления сервиса.',
        status: 'warning',
        duration: 3600,
      });
      await refreshSnapshot({ background: true });
      return null;
    } finally {
      setBusy('');
    }
  }, [build, notify, pollPublication, refreshSnapshot, stopPolling, threadId]);

  const openDiagnostic = useCallback(async (diagnostic) => {
    if (!project?.path || !diagnostic?.path || !onOpenSource) return false;
    const relative = String(diagnostic.path).replace(/^\/+/, '');
    return onOpenSource(`${project.path}/${relative}`, { line: diagnostic.line || null });
  }, [onOpenSource, project?.path]);

  return {
    profiles,
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
    project,
    authoring,
    build,
    busy,
    previewUrl,
    createProject,
    applyProfile,
    applyVendorOverlay,
    activateVendorProfile,
    buildProject,
    cancelBuild,
    openPreview,
    openDiagnostic,
    loadAuthoring,
    publish,
  };
}
