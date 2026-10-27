const { expect } = require('@playwright/test');

const THREAD = 'pdf-studio-fixture';
const PROJECT = '69a35f15-a7b9-5bb3-aef3-8b24d760a001';
const PROPOSAL = 'a'.repeat(32);

async function fixture(page, { absent = false, noProject = false, materials = false, semanticAbsent = false,
  presentation = false, sourceFailure = false, profileFailure = false, readGates = {}, blocks, providerStatus,
  initialSurface = 'pdf', title = 'Обзор методов машинного обучения', deniedThread = false, formatProfiles = null, sourceDigest } = {}) {
  const state = { writes: [], activations: 0, conflict: false, revision: 'revision-1', version: 1,
    requests: [], reads: [], copies: [], uploads: [], library: [], extraFiles: [],
    absent, noProject, profileFailure, preparations: [],
    factReads: { workspace: 0, project: 0, authoring: 0, profiles: 0 },
    builds: [], build: null, semanticReady: !semanticAbsent, leaseAcquisitions: 0, sourceReads: 0, sourceFailure,
    sources: [{ source_id: 1, title: 'Обзор методов обучения', year: '2024' }, { source_id: 2, title: 'Исследование качества моделей', year: '2025', doi: '10.1234/example' }] };
  if (materials) {
    state.library = [{ file_id: 'material-one', name: 'notes.txt', availability: 'ready', file_type: 'text/plain' }];
    state.extraFiles = [
      { path: 'documents/paper/content/002-intro.tex', type: 'file', size: 120 },
      { path: 'documents/paper/assets/chart.png', type: 'file', size: 240 },
    ];
  }
  const draft = {
    schema_version: 1, version: 1, title, blocks: blocks || [
      { block_id: 'heading', kind: 'section', title: 'Введение', text: '', level: 1 },
      { block_id: 'intro', kind: 'paragraph', title: '', text: 'Текст обзора для проверки редактора. Источники сохраняются вместе с документом.' },
      { block_id: 'closing', kind: 'paragraph', title: '', text: 'Неизменяемый заключительный раздел.' },
    ],
  };
  state.draft = draft;
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'synthetic-pdf-test-token');
  });
  await page.routeWebSocket('**/api/**', (socket) => {
    if (!socket.url().includes(`/chats/${THREAD}/`)) return;
    state.socket = socket;
    socket.onMessage((raw) => { const message = JSON.parse(raw); if (message.type === 'message') state.requests.push(message); });
  });
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (deniedThread && pathname === `/api/chats/${THREAD}/work`) {
      await route.fulfill({ status: 404, json: { detail: 'Thread not found' } }); return;
    }
    if (pathname.endsWith('/work')) state.factReads.workspace += 1;
    if (pathname.endsWith('/documents/status')) state.factReads.project += 1;
    if (pathname.endsWith('/documents/authoring')) state.factReads.authoring += 1;
    if (pathname.endsWith('/document-profiles')) state.factReads.profiles += 1;
    if (pathname.endsWith('/work')) await readGates.workspace;
    if (pathname.endsWith('/documents/status')) await readGates.project;
    if (pathname.endsWith('/documents/authoring')) await readGates.authoring;
    if (pathname.includes('/documents/proposals/')) await readGates.proposal;
    let json = {};
    if (pathname === '/api/chats/providers/status') {
      state.statusReads = (state.statusReads || 0) + 1;
      json = providerStatus || { state: 'available', ready: 2, total: 2, providers: [
        { id: 'gigachat', label: 'GigaChat', primary: true, state: 'ready' },
        { id: 'routerai', label: 'RouterAI', state: 'ready' },
        { id: 'openai', label: 'OpenAI', state: 'disabled' },
      ] };
    }
    if (pathname === '/api/profile/me') json = { id: 'pdf-user', email: 'pdf@example.test', permissions: [] };
    if (pathname === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: draft.title }] };
    if (pathname.endsWith('/ide/repositories')) json = { items: [], next_offset: null };
    if (pathname === `/api/chats/${THREAD}`) json = { messages: [] };
    if (pathname.endsWith(`/documents/proposals/${PROPOSAL}`)) json = state.proposal || {};
    if (pathname === `/api/chats/${THREAD}/trace`) json = { traces: {} };
    if (pathname === '/api/chats/personas') json = { personas: [{ id: 'engineer', label: 'Инженер', hint: 'Технические задачи' }] };
    if (pathname === '/api/chats/transcription/config') json = { enabled: false };
    if (pathname.startsWith('/api/chats/models')) json = pathname.endsWith('/catalog')
      ? { models: [{ id: 'GigaChat-2', context_window: 131072, capabilities: ['tools'] }], providers: [] }
      : { models: ['GigaChat-2'] };
    if (pathname === '/api/billing/balance') json = { total: 1598500 };
    if (pathname.endsWith('/work')) json = {
      contract_version: 2,
      workspace: { state: state.absent ? 'absent' : 'ready', revision: state.revision,
        entries: state.absent || state.noProject ? [] : [
          { path: `${state.projectPath || 'documents/paper'}/document.toml`, type: 'file', size: 100 },
          { path: `${state.projectPath || 'documents/paper'}/main.tex`, type: 'file', size: 250 },
          ...state.extraFiles,
        ], history: [] },
      library: { state: 'ready', items: state.library, next_cursor: null },
      room: { state: 'ready', leases: [], activity: [], control: { state: 'idle' } },
    };
    if (pathname.endsWith('/work/pdf/prepare')) {
      state.preparations.push(route.request().postDataJSON());
      await readGates.prepare;
      if (state.prepareFailure) { await route.fulfill({ status: state.prepareStatus || 503, json: state.prepareStatus === 404
        ? { detail: 'Not Found' } : { error: { code: 'pdf_preparation_unavailable', message: 'PDF preparation unavailable' } } }); return; }
      if (state.prepareExpired) { await route.fulfill({ json: { state: 'expired' } }); return; }
      state.absent = false; state.noProject = false;
      json = { state: 'ready', project_path: 'documents/paper', workspace: {
        state: 'ready', revision: state.revision, entries: [
          { path: 'documents/paper/document.toml', type: 'file', size: 100 },
          { path: 'documents/paper/main.tex', type: 'file', size: 250 }, ...state.extraFiles,
        ], history: [], truncated: false,
      } };
    }
    if (pathname.endsWith('/work/activate')) {
      state.activations += 1;
      if (state.activationFailure) { await route.fulfill({ status: 503, json: {} }); return; }
      state.absent = false; state.noProject = true; state.revision = 'new-workspace-revision';
      json = { contract_version: 2,
        workspace: { state: 'ready', revision: state.revision, entries: [], history: [], truncated: false },
        library: { state: 'ready', items: state.library, next_cursor: null },
        room: { state: 'ready', leases: [], activity: [], control: { state: 'idle' } } };
    }
    if (pathname.endsWith('/workspace/documents')) {
      const payload = route.request().postDataJSON();
      state.createdProjects = [...(state.createdProjects || []), payload];
      state.noProject = false; state.projectPath = payload.path; state.profileId = payload.profile_id;
      json = { path: payload.path, revision_changed: true, revision: state.revision };
    }
    if (pathname.endsWith('/document-profiles') && state.profileFailure) {
      await route.fulfill({ status: 503, json: { detail: 'document_profiles_unavailable' } }); return;
    }
    if (pathname.endsWith('/document-profiles')) json = { profiles: formatProfiles || [
      { profile_id: 'generic_document', label: 'Документ', paper: 'A4', orientation: 'portrait' },
      { profile_id: 'beamer_presentation', label: 'Презентация', paper: '16:9', orientation: 'landscape' },
    ] };
    if (pathname.endsWith('/documents/status')) json = {
      path: state.projectPath || 'documents/paper', project_id: PROJECT, revision: state.revision,
      kind: presentation ? 'presentation' : 'generic', mode: 'draft', locale: 'ru-RU',
      profile: { profile_id: state.profileId || 'generic_document', label: state.profileId === 'beamer_presentation' ? 'Презентация' : 'Документ' },
      authoring_state: state.semanticReady ? 'ready' : 'absent',
      authoring_version: state.semanticReady ? state.version : 0,
      draft_digest: state.semanticReady ? 'a'.repeat(64) : null, source_digest: sourceDigest, latest_build: state.build,
      vendor_overlays: state.vendorOverlays || [],
    };
    if (pathname.endsWith('/documents/authoring')) json = {
      authoring_version: state.version, draft_digest: 'a'.repeat(64), draft: state.draft,
      intent: { kind: 'generic', title: state.draft.title }, block_files: { intro: 'content/002-intro.tex' },
    };
    if (pathname.endsWith('/documents/sources')) {
      state.sourceReads += 1;
      await readGates.sources;
      if (state.sourceFailure) { await route.fulfill({ status: 503, json: {} }); return; }
      json = { revision: state.revision, sources: state.sources, unresolved_count: 0 };
    }
    if (pathname.endsWith('/documents/builds')) {
      state.builds.push(route.request().postDataJSON());
      await readGates.buildAdmission;
      state.build = { build_id: 'visible-build', state: 'queued', artifacts: [] };
      json = state.build;
    }
    if (pathname.endsWith('/documents/builds/visible-build')) json = state.build;
    if (pathname.endsWith('/documents/builds/visible-build/artifacts/visible-pdf')) {
      await route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' }); return;
    }
    if (pathname.endsWith('/documents/authoring/edit')) {
      state.writes.push(route.request().postDataJSON());
      if (state.conflict) { await route.fulfill({ status: 409, json: { detail: 'source_changed' } }); return; }
      state.version += 1; state.revision = `revision-${state.version}`;
      const submitted = state.writes.at(-1).draft;
      state.semanticReady = true;
      state.draft = { ...submitted, version: state.version, blocks: submitted.blocks
        || [{ block_id: 'intro', kind: 'paragraph', text: submitted.text || '' }] };
      json = { outcome: 'published', revision: state.revision, authoring_version: state.version, draft_digest: 'a'.repeat(64) };
    }
    if (pathname.endsWith('/leases/acquire')) {
      state.leaseAcquisitions += 1;
      json = { fence: 3, status: 'held', revision: state.revision };
    }
    if (pathname.endsWith('/workspace/file')) {
      const { path } = route.request().postDataJSON();
      state.reads.push(path);
      if (state.readFailure) { await route.fulfill({ status: 503, json: {} }); return; }
      json = { content: `Source of ${path}`, revision: state.revision };
    }
    if (pathname.endsWith('/work/library/material-one/copy')) {
      state.copies.push(route.request().postDataJSON());
      if (!state.extraFiles.some((item) => item.path === 'notes.txt')) state.extraFiles.push({ path: 'notes.txt', type: 'file', size: 12 });
      json = { outcome: 'imported' };
    }
    if (pathname.endsWith('/work/library/12345678-1234-1234-1234-123456789abc/copy')) {
      const payload = route.request().postDataJSON(); state.copies.push(payload);
      if (state.assetConflict) { await route.fulfill({ status: 409, json: { detail: 'source_changed' } }); return; }
      const asset = 'figures/library_12345678123412341234123456789abc.png';
      const destination = `${payload.document_path}/${asset}`;
      const existing = state.extraFiles.some((item) => item.path === destination);
      if (!existing) { state.extraFiles.push({ path: destination, type: 'file', size: 240 }); state.revision = 'revision-2'; }
      json = { outcome: existing ? 'kept' : 'imported', revision: state.revision, asset_path: asset };
    }
    if (pathname.endsWith('/work/upload')) {
      state.uploads.push(route.request().postDataBuffer().toString('utf8'));
      const file = { file_id: 'material-upload', name: 'uploaded.txt', availability: 'ready' };
      state.library = [...state.library.filter((item) => item.file_id !== file.file_id), file];
      if (!state.partialUpload) state.extraFiles.push({ path: 'uploaded.txt', type: 'file', size: 11 });
      json = { outcome: state.partialUpload ? 'library_saved' : 'imported', file };
    }
    if (pathname.endsWith('/work/library/upload')) {
      state.uploads.push(route.request().postDataBuffer().toString('utf8'));
      const file = { file_id: 'material-upload', name: 'uploaded.txt', availability: 'ready' };
      state.library = [...state.library.filter(item => item.file_id !== file.file_id), file];
      json = { outcome: 'library_uploaded', file };
    }
    if (pathname.endsWith('/workspace/issues')) json = { issues: [] };
    await route.fulfill({ json });
  });
  await page.goto(`/chat/${THREAD}${initialSurface === 'chat' ? '' : '?surface=pdf'}`, { waitUntil: 'domcontentloaded' });
  if (initialSurface === 'pdf') await expect(page.getByTestId('pdf-studio')).toBeVisible({ timeout: 20000 });
  else await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible({ timeout: 20000 });
  return state;
}

module.exports = { fixture, THREAD, PROJECT, PROPOSAL };
