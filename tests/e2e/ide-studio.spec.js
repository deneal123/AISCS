const { test, expect } = require('@playwright/test');
const axe = require('axe-core');
const { createHash } = require('node:crypto');
const { installVisualViewport } = require('./helpers/visualViewport');
const { openWorkbenchLibrary } = require('./helpers/workbenchLibrary');
const { questionFixture, parkQuestion, exerciseUnknownCostStop, SOURCE } = require('./helpers/humanQuestions');
test.use({ serviceWorkers: 'block' });
for (const width of [1440, 393]) test(`IDE unknown cost Stop ${width}px checks the same child without another run`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 700 });
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  if (width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const question = await questionFixture(page, { threadId: THREAD, projectId: A, surface: 'ide' });
  question.cost = { ...question.cost, state: 'pending', estimated_credits: 5000 };
  await parkQuestion(page, () => state.socket, question.snapshot, state.agentMessages);
  const mutations = [...state.mutations];
  await exerciseUnknownCostStop(page, question, state.agentMessages, info);
  expect(state.mutations).toEqual(mutations);
});
const { watchComposerGeometry, sampleComposerGeometry } = require('./helpers/composerGeometry');
const { checkComposerInvitation } = require('./helpers/actionHints');

for (const width of [1440, 393]) test(`IDE next-action input invitation survives peer changes ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  if (width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  for (const label of ['IDE', 'Чат', 'IDE']) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await checkComposerInvitation(page);
  }
});

for (const width of [1440, 393]) test(`IDE and Chat composer controls have final geometry from the first visible frame ${width}px`, async ({ page, browserName }) => {
  // Mobile WebKit can idle-throttle RAF to1Hz at this wide emulated viewport
  // (24-frame trace sample took23.8s). Retain all four samples and unchanged
  // per-action/readiness assertions, allowing time for the observation itself.
  if (browserName === 'webkit' && width === 1440) test.setTimeout(180000);
  await page.setViewportSize({ width, height: 900 });
  await watchComposerGeometry(page);
  await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  if (width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Не терять черновик IDE');
  for (const label of ['Чат', 'IDE', 'Чат', 'IDE']) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect(input).toBeVisible();
    expect(await sampleComposerGeometry(page)).toEqual({ mismatches: [], transitions: [] });
    await expect(input).toHaveValue('Не терять черновик IDE');
  }
});

for (const width of [1440, 393]) test(`IDE human question ${width}px replaces input and recovers one accepted child`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  if (width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const question = await questionFixture(page, { threadId: THREAD, projectId: A, surface: 'ide' });
  const panel = await parkQuestion(page, () => state.socket, question.snapshot, state.agentMessages);
  await expect(page.getByTestId('document-assistant-activity')).toHaveCount(0);
  const continueButton = panel.getByRole('button', { name: 'Продолжить', exact: true });
  await expect(continueButton).toBeDisabled();
  await continueButton.evaluate(button => {
    // Прочитать исходный disabled-стиль и зафиксировать первый enabled commit,
    // не ожидая завершения анимации прозрачности.
    getComputedStyle(button).opacity;
    const observer = new MutationObserver(() => {
      if (!button.disabled) {
        button.__firstEnabledOpacity = getComputedStyle(button).opacity;
        observer.disconnect();
      }
    });
    observer.observe(button, { attributes: true, attributeFilter: ['disabled'] });
  });
  await panel.getByRole('button', { name: 'Минимальная структура', exact: true }).click();
  expect(await continueButton.evaluate(button => button.__firstEnabledOpacity)).toBe('1');
  await expect(panel.getByRole('button', { name: 'Минимальная структура', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await panel.getByLabel('Свой ответ или детали').fill('Добавить README');
  await page.addScriptTag({ content: axe.source });
  expect(await page.evaluate(async () => (await window.axe.run(document.querySelector('[data-testid="human-question-panel"]'))).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
  await page.screenshot({ path: info.outputPath('ide-human-question.png'), animations: 'disabled' });
  question.loseAnswer = true;
  await panel.getByRole('button', { name: 'Продолжить', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Проверить состояние', exact: true })).toBeVisible();
  await expect(panel.getByLabel('Свой ответ или детали')).toHaveValue('Добавить README');
  await panel.getByRole('button', { name: 'Проверить состояние', exact: true }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  expect(question.answers).toHaveLength(1); expect(state.agentMessages).toHaveLength(1);
  expect(question.answers[0]).toMatchObject({ surface: 'ide', ide_context: { repository_id: A, generation: GENERATION },
    answer: { choice_id: 'small', text: 'Добавить README' } });
  const created = new Date(Date.now() + 1000).toISOString();
  question.history = [{ sender: 'assistant', created_at: created, content: 'Готово',
    metadata: { ide_repository: A, ide_summary: 'Структура подготовлена.', ide_files_written: 1 } }];
  question.taskState = 'SUCCESS';
  await expect(page.getByText('Структура подготовлена.', { exact: true })).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
  expect(question.answers).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('IDE reload restores an accepted question child without submitting an answer again', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 851 });
  const state = await fixture(page);
  const question = await questionFixture(page, { threadId: THREAD, projectId: A, surface: 'ide' });
  const child = '66666666-6666-4666-8666-666666666666';
  question.question = { ...question.snapshot, state: 'accepted', resume_job_id: child };
  question.history = [{ sender: 'user', content: 'Исходная задача', created_at: new Date().toISOString(), metadata: { ide_repository: A } },
    { sender: 'assistant', content: question.snapshot.prompt, created_at: new Date(Date.now() + 1).toISOString(),
      metadata: { ide_repository: A, human_question: question.snapshot, execution_status: 'waiting_user' } }];
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  await expect.poll(() => question.taskReads).toBeGreaterThan(0);
  expect(question.answers).toHaveLength(0); expect(state.agentMessages).toHaveLength(0);
  let stopped;
  await page.route(`**/api/jobs/v1/task/${child}/cancel`, async route => {
    stopped = new URL(route.request().url()).pathname;
    await route.fulfill({ json: { task_id: child, cancelled: true } });
  });
  await page.getByRole('button', { name: 'Остановить генерацию', exact: true }).click();
  await expect.poll(() => stopped).toBe(`/api/jobs/v1/task/${child}/cancel`);
  expect(stopped).not.toContain(SOURCE);
});

for (const width of [1440, 393]) test(`IDE continuation cost ${width}px waits for consent and recovers its lost acknowledgement`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  const state = await fixture(page);
  if (width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const question = await questionFixture(page, { threadId: THREAD, projectId: A, surface: 'ide' });
  question.cost = { ...question.cost, state: 'pending', estimated_credits: 5000, expires_at: new Date(Date.now() + 30000).toISOString() };
  const panel = await parkQuestion(page, () => state.socket, question.snapshot, state.agentMessages);
  await panel.getByRole('button', { name: 'Минимальная структура', exact: true }).click();
  await panel.getByRole('button', { name: 'Продолжить', exact: true }).click();
  const consent = page.getByRole('region', { name: 'Подтверждение стоимости', exact: true });
  await expect(consent.getByText('До 5 000 кредитов', { exact: true })).toBeVisible();
  await expect(consent.getByRole('heading', { name: 'До 5 000 кредитов', exact: true })).toBeInViewport({ ratio: 1 });
  await expect(consent.getByRole('button', { name: 'Не запускать', exact: true })).toBeFocused();
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toHaveCount(0);
  expect(question.taskReads).toBe(0); expect(question.decisions).toHaveLength(0);
  await consent.evaluate(node => node.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(question.decisions).toHaveLength(0);
  await page.addScriptTag({ content: axe.source });
  expect(await page.evaluate(async () => (await window.axe.run(document.querySelector('[data-testid="human-question-panel"]'))).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
  const bounds = await consent.boundingBox();
  const before = await consent.getByRole('button', { name: 'Подтвердить запуск', exact: true }).boundingBox();
  await page.screenshot({ path: info.outputPath('ide-continuation-cost.png'), animations: 'disabled' });
  question.loseDecision = true;
  await consent.getByRole('button', { name: 'Подтвердить запуск', exact: true }).click();
  const check = consent.getByRole('button', { name: 'Проверить состояние', exact: true });
  await expect(check).toBeVisible();
  await expect(consent.getByText('Ответ сохранён. Состояние продолжения нужно проверить.', { exact: true })).toBeVisible();
  expect(await consent.boundingBox()).toEqual(bounds);
  expect(await check.boundingBox()).toEqual(before);
  expect(question.decisions).toHaveLength(1); expect(question.answers).toHaveLength(1);
  expect(question.taskReads).toBe(0);
  await check.click();
  await expect(consent).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  await expect.poll(() => question.taskReads).toBeGreaterThan(0);
  expect(question.decisions).toEqual([{ offer_id: '88888888-8888-4888-8888-888888888888', decision: 'accept' }]);
  expect(state.agentMessages).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

const THREAD = '10000000-0000-0000-0000-000000000001';
const A = '20000000-0000-0000-0000-000000000001';
const B = '20000000-0000-0000-0000-000000000002';
const C = '20000000-0000-0000-0000-000000000003';
const GENERATION = 'a'.repeat(64);
const LIBRARY_FILE = '40000000-0000-0000-0000-000000000001';
const names = ['Первый репозиторий', 'Второй репозиторий с очень длинным названием для проверки компоновки'];
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };

async function fixture(page, { initialSurface = 'work', listGate, prepareGate, library = false, recoveredAttempt = null, failRecovery = false, preparePending = false, empty = false, failList = false, failPrepare = false, deniedThread = false, savedProjects = false, pendingCheckpoint = null } = {}) {
  const state = { reads: [], mutations: [], preparations: [], descriptorsCreated: 0, recoveredAttempt, failRecovery, failPrepare, failFile: false, runtimeState: 'ready', legacyReads: 0, failList, created: false, files: new Map(), entries: [
    { path: 'src', type: 'dir', size: 0, incomplete: false },
    { path: 'src/вложенная-папка-с-длинным-именем', type: 'dir', size: 0, incomplete: true },
    { path: 'src/main.py', type: 'file', size: 200, incomplete: false },
    { path: 'src/helpers.py', type: 'file', size: 200, incomplete: false },
  ] };
  state.savedVersions = pendingCheckpoint ? [pendingCheckpoint] : [];
  state.checkpointStatus = pendingCheckpoint ? { ...pendingCheckpoint, collected: false } : null;
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'synthetic-ide-fixture');
  });
  state.agentMessages = [];
  state.library = library ? [{ file_id: LIBRARY_FILE, name: 'asset.zip', availability: 'ready', file_type: 'archive' }] : [];
  state.libraryCopies = []; state.libraryUploads = [];
  state.fileWrites = [];
  state.generation = GENERATION; state.leaseActions = [];
  await page.routeWebSocket('**/api/**', (socket) => {
    state.socket = socket;
    socket.onMessage(raw => { const message = JSON.parse(String(raw)); if (message.type === 'message') state.agentMessages.push(message); });
  });
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (deniedThread && path === `/api/chats/${THREAD}/ide/repositories`) {
      await route.fulfill({ status: 404, json: { detail: 'ide_repository_not_found' } }); return;
    }
    let json = {};
    if (path.endsWith('/console') && request.method() === 'POST') {
      state.consoleCommands = [...(state.consoleCommands || []), request.postDataJSON()];
      const payload = state.consoleCommands.at(-1);
      state.consoleReceipt = { execution_id: payload.execution_id, repository_id: A, generation: state.generation,
        state: 'completed', result: { exit_code: 0, stdout: state.consoleOutput || 'Hello, world!\n', stderr: '', duration_sec: 0.1, truncated: false, timed_out: false } };
      if (state.consoleGate) await state.consoleGate;
      if (state.consoleLost) { state.consoleLost = false; await route.abort(); return; }
      json = state.consoleReceipt;
    }
    if (path.includes('/console/') && request.method() === 'GET') json = state.consoleReceipt;
    if (path === '/api/profile/me') json = { id: 'ide-user', email: 'ide@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: 'Пространство разработки' }] };
    if (path === `/api/chats/${THREAD}`) json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path === '/api/chats/transcription/config') json = { enabled: false };
    if (path === '/api/chats/personas') json = { personas: [] };
    if (path.startsWith('/api/chats/models')) json = path.endsWith('/catalog') ? { models: [], providers: [] } : { models: [] };
    if (path === '/api/chats/providers/status') json = { state: 'available', ready: 1, total: 1, providers: [{ id: 'gigachat', label: 'GigaChat', primary: true, state: 'ready' }] };
    if (path === '/api/billing/balance') json = { total: 1000 };
    if (path.endsWith('/work')) { state.legacyReads += 1; json = { contract_version: 2, workspace: { state: 'absent', entries: [] }, library: { state: 'ready', items: state.library }, room: {} }; }
    if (path.endsWith('/work/library/upload')) {
      const form = request.postDataBuffer().toString('utf8');
      expect(form).toContain('upload_intent_id');
      expect(form).not.toContain('name="expected_revision"'); expect(form).not.toContain('name="fence"');
      state.libraryUploads.push(path);
      const item = { file_id: '40000000-0000-0000-0000-000000000002', name: 'upload.txt', availability: 'ready', file_type: 'text' };
      state.library.push(item); json = { outcome: 'library_uploaded', workspace_status: 'not_requested', file: item };
    }
    if (path.endsWith('/ide/prepare')) {
      const payload = request.postDataJSON();
      expect(request.headers()['x-workspace-session']).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
      expect(Object.keys(payload)).toEqual(payload.repository_id ? ['repository_id'] : []);
      state.preparations.push(payload);
      if (!payload.repository_id && !state.created) state.descriptorsCreated += 1;
      state.created = true;
      await prepareGate;
      if (payload.repository_id && state.continuationGate) await state.continuationGate.promise;
      if (state.failPrepare) { await route.fulfill({ status: 503, json: { detail: 'PRIVATE_PREPARATION' } }); return; }
      const pending = preparePending && state.preparations.length === 1;
      state.runtimeState = pending ? 'pending' : 'ready';
      const id = payload.repository_id || A;
      json = { repository: { repository_id: id, name: names[id === A ? 0 : 1], state: 'registered' },
        runtime: { repository_id: id, workspace: { state: state.runtimeState, expires_at: 9999999999, can_retry: false } },
        git: pending ? null : { initialized: true, branch: 'main' } };
      if (id === C) json.repository.name = 'Клон проекта';
    } else if (path.includes('/ide/clones')) {
      state.isolatedClones ||= [];
      if (request.method() === 'POST') {
        state.isolatedClones.push(request.postDataJSON());
        await state.cloneGate?.promise;
        if (state.cloneAckLost) { await route.fulfill({ status: 503, json: {} }); return; }
      }
      if (state.recoveredAttempt) {
        if (request.method() === 'POST') state.recoveredAttempt = { ...state.recoveredAttempt, state: 'complete' };
        json = { state: state.recoveredAttempt.state, repository: state.recoveredAttempt.repository, code: null };
      } else json = { state: 'complete', repository: { repository_id: C, name: 'Клон проекта', state: 'registered' }, code: null };
    } else if (path.endsWith('/ide/repositories')) {
      state.reads.push(path); await listGate;
      if (request.method() === 'POST') {
        state.created = true;
        state.runtimeState = 'not_created';
        const payload = request.postDataJSON();
        expect(payload.create_thread_if_missing).toBe(true);
        expect(payload.creation_intent_id).toMatch(/^[a-f0-9-]{36}$/);
        json = { repository_id: A, name: payload.name, state: 'registered' };
      } else {
        if (state.failList) { await route.fulfill({ status: 503, json: {} }); return; }
        json = { items: empty && !state.created ? [] : [A, B].map((id, index) => ({ repository_id: id, name: names[index], state: 'registered' })), next_offset: null };
      }
    } else if (path.includes('/ide/')) {
      state.reads.push(path);
      const id = path.includes(A) ? A : path.includes(C) ? C : B;
      if (path.endsWith('/agent-commands')) {
        expect(request.method()).toBe('GET');
        expect(new URL(request.url()).searchParams.get('generation')).toBe(state.generation);
        json = { repository_id: id, generation: state.generation, entries: [] };
      }
      else if (path.endsWith('/checkpoints/capabilities')) json = { enabled: savedProjects };
      else if (path.endsWith('/checkpoints')) {
        state.savedVersions ||= []; state.saves ||= [];
        if (request.method() === 'POST') {
          const intent = request.postDataJSON(); state.saves.push(intent);
          const item = { checkpoint_id: intent.checkpoint_id, state: 'published', is_current: true, size_bytes: 2048, created_at: '2026-10-18T17:00:00Z' };
          state.savedVersions = [item, ...state.savedVersions.map(row => ({ ...row, is_current: false }))]; json = { repository_id: id, ...item };
        } else json = { repository_id: id, items: state.savedVersions, truncated: false,
          usage: { used_bytes: state.savedVersions.length * 2048, max_bytes: 1073741824, max_snapshot_bytes: 67108864 },
          runtime: { generation: state.generation, state: state.runtimeState }, last_restore: null };
      }
      else if (path.endsWith('/restores')) {
        state.restores ||= []; state.restores.push(request.postDataJSON());
        state.runtimeState = 'ready'; state.generation = 'b'.repeat(64);
        json = { repository_id: id, ...request.postDataJSON(), state: 'published', active: true, generation: state.generation };
      }
      else if (/\/checkpoints\/[a-f0-9-]{36}(?:\/(discard|reconcile|abandon))?$/.test(path)) {
        state.checkpointStatusReads ||= []; state.discards ||= [];
        const checkpointId = path.match(/\/checkpoints\/([a-f0-9-]{36})/)[1];
        if (path.endsWith('/abandon')) {
          state.abandons ||= []; state.abandons.push(checkpointId);
          expect(request.postDataJSON()).toEqual({}); await state.abandonGate?.promise;
          state.checkpointStatus = { ...state.checkpointStatus, state: 'retired', can_abandon: false };
          state.savedVersions = state.savedVersions.map(row => row.checkpoint_id === checkpointId ? { ...row, ...state.checkpointStatus } : row);
          if (state.abandonAckLost) { await route.abort(); return; }
        } else if (path.endsWith('/discard')) {
          expect(request.postDataJSON()).toEqual({}); state.discards.push(checkpointId);
          await state.discardGate?.promise;
          state.checkpointStatus = { ...state.checkpointStatus, state: 'retired', collected: true, can_discard: false, is_current: false, cleanup_pending: false };
          state.savedVersions = state.savedVersions.filter(item => item.checkpoint_id !== checkpointId);
          if (state.discardAckLost) { await route.abort(); return; }
        } else if (path.endsWith('/reconcile') && state.unreadableCheckpoint) {
          await route.fulfill({ status: 503, json: { detail: 'ide_checkpoint_storage_unavailable' } }); return;
        } else state.checkpointStatusReads.push(checkpointId);
        json = { repository_id: id, checkpoint_id: checkpointId, ...state.checkpointStatus };
      }
      else if (path.endsWith('/clone-attempt')) {
        if (state.failRecovery) { await route.fulfill({ status: 503, json: { detail: 'PRIVATE_CLONE_RECOVERY' } }); return; }
        json = { attempt: state.recoveredAttempt || null };
      }
      else if (path.includes('/library/') && path.endsWith('/copy')) {
        state.libraryCopies.push({ repository_id: id, ...request.postDataJSON() });
        if (state.copyAckLost) { await route.fulfill({ status: 503, json: { detail: 'PRIVATE_COPY_FAILURE' } }); return; }
        const payload = request.postDataJSON();
        state.entries.push({ path: payload.path, type: 'file', size: 300000, incomplete: false });
        json = { repository_id: id, generation: GENERATION, path: payload.path, kind: 'file', size: 300000, digest: 'b'.repeat(64), written: true };
      }
      else if (path.endsWith('/runtime')) {
        if (state.runtimeGate) await state.runtimeGate.promise;
        if (state.failRuntime) { await route.fulfill({ status: 503, json: { detail: 'PRIVATE_RUNTIME_FAILURE' } }); return; }
        if (request.method() === 'POST') state.runtimeState = 'ready';
        json = { repository_id: id, workspace: { state: state.runtimeState, expires_at: state.runtimeState === 'not_created' ? null : 9999999999, can_retry: false } };
      }
      else if (path.endsWith('/files/tree')) json = { repository_id: id, generation: state.generation, entries: state.entries, truncated: true };
      else if (path.endsWith('/git')) {
        if (state.cloneConflict && request.postDataJSON().operation === 'clone') {
          state.currentCloneCalls = (state.currentCloneCalls || 0) + 1;
          await route.fulfill({ status: 409, json: { error: { code: 'ide_git_not_empty', message: 'ide_git_not_empty' } } }); return;
        }
        json = { repository_id: id, generation: state.generation, initialized: true, branch: 'main' };
      }
      else if (path.endsWith('/agent/target')) {
        expect(request.postDataJSON()).toEqual({ generation: GENERATION });
        if (state.targetGate) await state.targetGate.promise;
        json = { target_id: '30000000-0000-0000-0000-000000000001', expires_in: 120 };
      }
      else if (path.endsWith('/files/lease')) { const payload = request.postDataJSON(); state.leaseActions.push(payload); json = { repository_id: id, generation: state.generation, path: payload.path, fence: 1, expires_at: 9999999999 }; }
      else if (path.endsWith('/files/write')) {
        const payload = request.postDataJSON(); state.fileWrites.push(payload);
        if (state.writeConflict) { await route.fulfill({ status: 409, json: { error: { code: 'ide_file_changed' } } }); return; }
        state.files.set(payload.path, payload.content);
        if (!state.entries.some(item => item.path === payload.path)) state.entries.push({ path: payload.path, type: payload.operation === 'directory' ? 'dir' : 'file', size: payload.content.length, incomplete: false });
        if (state.writeAckLost) { await route.fulfill({ status: 503, json: { detail: 'PRIVATE_WRITE_FAILURE' } }); return; }
        json = { repository_id: id, generation: GENERATION, path: payload.path, kind: payload.operation === 'directory' ? 'dir' : 'file', digest: payload.operation === 'directory' ? null : createHash('sha256').update(payload.content).digest('hex'), size: Buffer.byteLength(payload.content), written: true };
      }
      else if (path.endsWith('/files/move')) {
        const payload = request.postDataJSON();
        state.fileMoves ||= []; state.fileMoves.push(payload);
        if (state.failMove) { await route.fulfill({ status: 503, json: { detail: 'ide_write_unconfirmed' } }); return; }
        const directory = state.entries.find(item => item.path === payload.path)?.type === 'dir';
        if (state.entries.some(item => item.path === payload.destination)) { await route.fulfill({ status: 409, json: { detail: 'ide_file_changed' } }); return; }
        const retarget = value => value === payload.path || value.startsWith(`${payload.path}/`) ? payload.destination + value.slice(payload.path.length) : value;
        state.entries = state.entries.map(item => ({ ...item, path: retarget(item.path) }));
        state.files = new Map([...state.files].map(([key, content]) => [retarget(key), content]));
        json = { repository_id: id, generation: GENERATION, path: payload.destination, moved_from: payload.path, size: directory ? 0 : 3, moved: true };
      }
      else if (path.endsWith('/files/read')) {
        if (state.failFile) { await route.fulfill({ status: 503, json: { detail: 'PRIVATE_BODY' } }); return; }
        const payload = request.postDataJSON();
        expect(state.entries.map(item => item.path)).toContain(payload.path);
        expect(payload.generation).toBe(state.generation);
        const content = state.files.get(payload.path) ?? (`# ${id === A ? 'Проект A' : 'Проект B'}\n# ${payload.path}\ndef greet():\n    return 'hello'\n` + '# long line '.repeat(40));
        json = { repository_id: id, generation: state.generation, path: payload.path, kind: 'text', content,
          digest: createHash('sha256').update(content).digest('hex'), size: Buffer.byteLength(content), truncated: false };
      } else state.mutations.push(path);
    }
    if (request.method() === 'POST' && !path.endsWith('/ide/prepare') && !path.endsWith('/files/tree') && !path.endsWith('/files/read') && !(path.endsWith('/git') && request.postDataJSON().operation === 'status')) state.mutations.push(path);
    await route.fulfill({ json });
  });
  await page.goto(`/chat/${THREAD}${initialSurface === 'chat' ? '' : '?surface=work&keep=1'}`);
  if (initialSurface !== 'chat') await expect(page.getByTestId('ide-studio')).toBeVisible();
  else await expect(page.getByRole('button', { name: 'IDE', exact: true })).toBeVisible();
  return state;
}

test('cold IDE chunk loading stays visible and Chat navigation remains usable', async ({ page }, info) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const held = deferred();
  let chunks = 0;
  await page.route('**/static/js/*.chunk.js', async route => {
    const response = await route.fetch();
    const body = await response.body();
    if (/['"]ide-studio['"]/.test(body.toString('utf8'))) { chunks += 1; await held.promise; }
    await route.fulfill({ response, body });
  });
  try {
    const state = await fixture(page, { initialSurface: 'chat' });
    await page.getByRole('button', { name: 'IDE', exact: true }).click();
    const loading = page.getByRole('status').filter({ hasText: 'Загружаю рабочее место…' });
    await expect(loading).toBeVisible();
    await expect(loading).not.toContainText('%');
    await expect(loading.locator('.chakra-spinner')).toHaveCSS('animation-name', 'none');
    await expect.poll(() => chunks).toBe(1);
    await page.getByRole('button', { name: 'Чат', exact: true }).click();
    await expect(loading).toBeHidden();
    held.resolve();
    await page.getByTestId('ide-studio').waitFor({ state: 'attached' });
    expect(state.preparations).toHaveLength(0);
    await page.getByRole('button', { name: 'IDE', exact: true }).click();
    await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath('cold-ide-recovered.png') });
  } finally { held.resolve(); }
});

async function selectFile(page) {
  await page.getByRole('button', { name: 'src', exact: true }).click();
  await page.getByRole('button', { name: 'src/main.py', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Просмотр исходника', exact: true })).toBeFocused();
}

for (const width of [1440, 393]) test(`console ${width}px runs explicitly, resizes independently and reconciles without replay`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 });
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  const agent = page.locator('[data-testid="ide-workbench-panels"]').locator('> div').last();
  const before = width === 1440 ? await agent.boundingBox() : null;
  if (width < 1100) await page.getByRole('button', { name: 'Код', exact: true }).click();
  const console = page.getByRole('region', { name: 'Консоль разработчика', exact: true });
  await expect(console).toBeVisible();
  await expect(page.getByRole('button', { name: 'Консоль', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect(state.consoleCommands || []).toHaveLength(0);
  const separator = page.getByRole('separator', { name: 'Высота редактора и консоли', exact: true });
  const height = (await console.boundingBox()).height;
  await separator.focus(); await page.keyboard.press('ArrowUp'); await page.keyboard.press('ArrowUp');
  expect((await console.boundingBox()).height).toBeGreaterThan(height);
  if (width === 1440) {
    const bounds = await separator.boundingBox();
    const previousHeight = (await console.boundingBox()).height;
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await page.mouse.down(); await page.mouse.move(bounds.x + bounds.width / 2, bounds.y - 30); await page.mouse.up();
    expect((await console.boundingBox()).height).toBeGreaterThan(previousHeight);
  }
  if (before) {
    const after = await agent.boundingBox();
    expect(after.height).toBeCloseTo(before.height, 0);
    expect(after.width).toBeCloseTo(before.width, 0);
  }
  const input = console.getByRole('textbox', { name: 'Команда консоли', exact: true });
  await input.fill('python src/hello_world.py');
  state.consoleLost = true;
  await console.getByRole('button', { name: 'Выполнить команду', exact: true }).click();
  await expect(console.getByText('Результат пока не получен.', { exact: false })).toBeVisible();
  await console.getByRole('button', { name: 'Проверить результат', exact: true }).click();
  await expect(console.getByText('Hello, world!', { exact: true })).toBeVisible();
  await expect(console.getByText('Код завершения: 0', { exact: true })).toBeVisible();
  expect(state.consoleCommands).toHaveLength(1);
  expect(state.agentMessages).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('ide-console.png'), animations: 'disabled' });
  await console.getByRole('button', { name: 'Свернуть консоль', exact: true }).click();
  await expect(console).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Консоль', exact: true })).toBeFocused();
});

test('mobile regression: clone body scrolls with keyboard and command placeholder fits', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 851 });
  await installVisualViewport(page);
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Код', exact: true }).click();
  await page.evaluate(() => document.documentElement.style.setProperty('--app-safe-bottom', '34px'));
  const command = page.getByRole('textbox', { name: 'Команда консоли', exact: true });
  await expect(command).toHaveAttribute('placeholder', 'Команда…');
  const inputBounds = await command.boundingBox();
  expect(inputBounds.width).toBeGreaterThan(180);
  const submit = page.getByRole('button', { name: 'Выполнить команду', exact: true });
  const submitBounds = await submit.boundingBox();
  expect(submitBounds.x).toBeGreaterThanOrEqual(inputBounds.x + inputBounds.width);
  await page.getByRole('button', { name: 'Свернуть консоль', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Просмотр исходника', exact: true })).toHaveCSS('padding-bottom', '34px');
  await page.getByRole('button', { name: 'Файлы', exact: true }).click();
  await page.getByRole('button', { name: 'Клонировать по ссылке', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const origin = dialog.getByLabel('Ссылка на репозиторий', { exact: true });
  await origin.fill('https://github.com/example/project');
  await page.evaluate(() => window.setTestVisualViewport(360, 30));
  const body = dialog.locator('.chakra-modal__body');
  await expect.poll(() => body.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await body.evaluate(element => { element.scrollTop = element.scrollHeight; });
  const help = dialog.locator('#ide-clone-help');
  const helpBounds = await help.boundingBox();
  const cancelBounds = await dialog.getByRole('button', { name: 'Отмена', exact: true }).boundingBox();
  expect(helpBounds.y + helpBounds.height).toBeLessThanOrEqual(cancelBounds.y);
  expect(cancelBounds.y + cancelBounds.height).toBeLessThanOrEqual(390);
  await expect(origin).toHaveValue('https://github.com/example/project');
  await page.screenshot({ path: info.outputPath('mobile-clone-keyboard.png') });
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  expect(state.consoleCommands || []).toHaveLength(0);
});

test('warnings and long console output never change workbench panel geometry', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const state = await fixture(page, { failRecovery: true });
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  const panels = [page.getByTestId('ide-workbench-panels'), page.getByTestId('ide-agent-pane'),
    page.getByTestId('ide-console'), page.getByRole('complementary', { name: 'Файлы репозитория', exact: true })];
  const geometry = async () => Promise.all(panels.map(panel => panel.boundingBox()));
  const before = await geometry();
  state.consoleOutput = 'Длинная строка лога '.repeat(300) + '\nстрока\n'.repeat(200);
  await page.getByRole('textbox', { name: 'Команда консоли', exact: true }).fill('python main.py');
  await page.getByRole('button', { name: 'Выполнить команду', exact: true }).click();
  await expect(page.getByText('Код завершения: 0', { exact: true })).toBeVisible();
  state.failList = true; state.failRuntime = true;
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const status = page.getByRole('button', { name: 'Состояние IDE', exact: true });
  await expect(status).toHaveAttribute('title', /[3-9] уведомлений/);
  expect(await geometry()).toEqual(before);
  await status.click();
  await expect(page.getByText('Не удалось прочитать среду. Ранее загруженные исходники остаются доступными.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Проверить клонирование', exact: true })).toBeVisible();
  expect(await geometry()).toEqual(before);
  expect(state.agentMessages).toHaveLength(0);
  await page.screenshot({ path: info.outputPath('ide-stable-warnings.png'), animations: 'disabled' });
});

for (const runtimeState of ['expired', 'unknown']) test(`runtime ${runtimeState} preserves a copyable draft without navigation or a replacement workspace`, async ({ page }, testInfo) => {
  const state = await fixture(page);
  await selectFile(page);
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Содержимое src/main.py', exact: true });
  await input.fill('retained local text');
  const preparations = state.preparations.length;
  state.runtimeState = runtimeState;
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByText(runtimeState === 'expired' ? 'Срок среды истёк' : 'Состояние среды не подтверждено', { exact: true })).toBeVisible();
  await expect(input).toHaveValue('retained local text');
  await expect(input).toHaveAttribute('readonly', '');
  await expect(page.getByRole('button', { name: 'Получить право', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Сверить с файлом', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Записать в среду', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Запустить среду', exact: true })).toHaveCount(0);
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.__copiedIdeDraft = text; } } }));
  await page.getByRole('button', { name: 'Скопировать черновик', exact: true }).click();
  expect(await page.evaluate(() => window.__copiedIdeDraft)).toBe('retained local text');
  expect(state.fileWrites).toEqual([]);
  expect(state.preparations).toHaveLength(preparations);
  expect(state.agentMessages).toEqual([]);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[data-testid="ide-studio"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`ide-runtime-${runtimeState}.png`), animations: 'disabled' });
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  const guard = page.getByRole('alertdialog');
  await expect(guard).toBeVisible();
  await guard.getByRole('button', { name: 'Продолжить редактирование', exact: true }).click();
  await expect(input).toHaveValue('retained local text');
});

test('runtime verification pauses writes and a replacement source is adopted only explicitly', async ({ page }) => {
  const state = await fixture(page);
  await selectFile(page);
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Содержимое src/main.py', exact: true });
  await input.fill('my draft');
  const gate = deferred(); state.runtimeGate = gate; state.failRuntime = true;
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  await expect(input).toHaveAttribute('readonly', '');
  await expect(input).toHaveValue('my draft');
  await expect(page.getByRole('button', { name: 'Записать в среду', exact: true })).toBeDisabled();
  state.runtimeGate = null; gate.resolve();
  await page.getByRole('button', { name: 'Состояние IDE', exact: true }).click();
  await expect(page.getByText('Не удалось прочитать среду. Ранее загруженные исходники остаются доступными.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Закрыть состояние IDE', exact: true }).click();
  await expect(page.getByTestId('ide-studio')).not.toContainText('PRIVATE_RUNTIME_FAILURE');
  state.failRuntime = false; state.generation = 'c'.repeat(64); state.files.set('src/main.py', 'replacement source');
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await expect(input).toHaveValue('my draft');
  await expect(page.getByRole('button', { name: 'Получить право', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Сверить с файлом', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Сравнение версий файла' })).toContainText('replacement source');
  await expect(input).toHaveValue('my draft');
  await page.getByRole('button', { name: 'Загрузить версию', exact: true }).click();
  await expect(input).toHaveValue('replacement source');
  await page.getByRole('button', { name: 'Получить право', exact: true }).click();
  await expect(input).toBeEditable();
  expect(state.leaseActions.at(-1)).toMatchObject({ action: 'acquire', generation: 'c'.repeat(64) });
  expect(state.fileWrites).toEqual([]);
});

test('editor recovery compares a conflicting source without rebasing or losing the draft', async ({ page }, testInfo) => {
  const state = await fixture(page);
  await selectFile(page);
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Содержимое src/main.py', exact: true });
  await input.fill('print("my draft")');
  state.writeConflict = true;
  await page.getByRole('button', { name: 'Записать в среду', exact: true }).click();
  await expect(input).toHaveAttribute('readonly', '');
  await expect(input).toHaveValue('print("my draft")');
  state.files.set('src/main.py', 'print("someone else")');
  state.writeConflict = false;
  await page.getByRole('button', { name: 'Получить право', exact: true }).click();
  const recovery = page.getByRole('region', { name: 'Сверка файла', exact: true });
  await expect(recovery.getByRole('region', { name: 'Сравнение версий файла' })).toContainText('someone else');
  await expect(input).toHaveValue('print("my draft")');
  await expect(page.getByRole('button', { name: 'Записать в среду', exact: true })).toBeDisabled();
  expect((await input.boundingBox()).height).toBeGreaterThanOrEqual(80);
  expect(state.fileWrites).toHaveLength(1);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[data-testid="ide-studio"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('ide-editor-conflict.png'), animations: 'disabled' });
  await recovery.getByRole('button', { name: 'Загрузить версию', exact: true }).click();
  await expect(input).toHaveValue('print("someone else")');
  await expect(input).toBeFocused();
  await page.getByRole('button', { name: 'Получить право', exact: true }).click();
  await expect(input).toBeEditable();
  await page.getByRole('button', { name: 'Отменить', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toContainText('someone else');
  expect(state.fileWrites).toHaveLength(1);
});

test('editor recovery reconciles a lost write acknowledgement by read without repeating the write', async ({ page }, testInfo) => {
  const state = await fixture(page);
  await selectFile(page);
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Содержимое src/main.py', exact: true });
  await input.fill('print("written once")');
  state.writeAckLost = true;
  await page.getByRole('button', { name: 'Записать в среду', exact: true }).click();
  const recovery = page.getByRole('region', { name: 'Сверка файла', exact: true });
  await expect(recovery).toBeVisible();
  await expect(input).toHaveValue('print("written once")');
  await expect(page.getByTestId('ide-studio')).not.toContainText('PRIVATE_WRITE_FAILURE');
  await recovery.getByRole('button', { name: 'Сверить с файлом', exact: true }).click();
  await expect(recovery).toContainText('Сейчас файл в среде совпадает с вашим текстом');
  await expect(input).toHaveValue('print("written once")');
  await expect(page.getByText('Есть несохранённые изменения.', { exact: true })).toBeVisible();
  expect(state.fileWrites).toHaveLength(1);
  await recovery.getByRole('button', { name: 'Загрузить версию', exact: true }).click();
  await expect(page.getByText('Есть несохранённые изменения.', { exact: true })).toHaveCount(0);
  expect(state.fileWrites).toHaveLength(1);
  expect(state.agentMessages).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('ide-editor-readback.png'), animations: 'disabled' });
});

test('editor recovery retains the draft when source comparison fails and allows another explicit read', async ({ page }) => {
  const state = await fixture(page);
  await selectFile(page);
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Содержимое src/main.py', exact: true });
  await input.fill('my draft');
  state.writeConflict = true;
  await page.getByRole('button', { name: 'Записать в среду', exact: true }).click();
  const recovery = page.getByRole('region', { name: 'Сверка файла', exact: true });
  await expect(recovery).toBeVisible();
  state.failFile = true;
  await recovery.getByRole('button', { name: 'Сверить с файлом', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Не удалось сверить файл');
  await expect(recovery.getByRole('button', { name: 'Загрузить версию', exact: true })).toBeDisabled();
  await expect(input).toHaveValue('my draft');
  state.failFile = false;
  await recovery.getByRole('button', { name: 'Сверить с файлом', exact: true }).click();
  await expect(recovery.getByRole('button', { name: 'Загрузить версию', exact: true })).toBeEnabled();
  await expect(input).toHaveValue('my draft');
  expect(state.fileWrites).toHaveLength(1);
});

test('Library opened during IDE preparation never defaults to creating a legacy workspace', async ({ page }) => {
  const gate = deferred();
  const state = await fixture(page, { library: true, prepareGate: gate.promise });
  const panel = await openWorkbenchLibrary(page);
  await expect(panel.getByText('Проверяю назначение IDE. Добавление станет доступно после готовности репозитория.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Добавить asset.zip в IDE', exact: true })).toBeDisabled();
  gate.resolve();
  await expect(panel.getByText(`IDE: ${names[0]}`, { exact: true })).toBeVisible();
  expect(state.libraryCopies).toEqual([]);
  expect(state.mutations).toEqual([]);
});

test('Library copies to the named IDE repository only after an explicit destination submit', async ({ page }, testInfo) => {
  const state = await fixture(page, { library: true });
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  const panel = await openWorkbenchLibrary(page);
  await expect(panel.getByText(`IDE: ${names[0]}`, { exact: true })).toBeVisible();
  const target = panel.getByRole('combobox', { name: 'Куда добавить файл', exact: true });
  await target.focus(); await target.press('ArrowDown');
  await expect(page.getByRole('option', { name: `IDE: ${names[0]}`, exact: true })).toBeVisible();
  await target.press('Escape');
  await panel.getByRole('button', { name: 'Добавить asset.zip в IDE', exact: true }).click();
  const form = panel.getByTestId('ide-library-copy');
  const path = form.getByLabel('Путь назначения');
  await expect(path).toBeFocused(); await expect(path).toHaveValue('asset.zip');
  expect(state.libraryCopies).toEqual([]);
  await path.fill('../invalid');
  await form.getByRole('button', { name: 'Добавить в IDE', exact: true }).click();
  await expect(form.getByText('Введите относительный путь без «..» и служебных каталогов.')).toBeVisible();
  await expect(path).toBeFocused();
  await path.fill('src/asset.zip');
  await page.screenshot({ path: testInfo.outputPath('ide-library-destination.png'), animations: 'disabled' });
  await form.getByRole('button', { name: 'Добавить в IDE', exact: true }).click();
  await expect(form.getByRole('status')).toContainText('Файл добавлен в IDE: src/asset.zip');
  await expect(panel.getByText('Сохраните правки и дождитесь готовности репозитория IDE перед копированием.')).toHaveCount(0);
  expect(state.libraryCopies).toEqual([{ repository_id: A, path: 'src/asset.zip', generation: GENERATION, fence: 1 }]);
  expect(state.agentMessages).toEqual([]);
  expect(state.mutations.filter(path => path.includes('/work/') || path.endsWith('/files/write'))).toEqual([]);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[data-testid="workbench-library"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('unknown Library copy acknowledgement keeps the path locked without a second POST', async ({ page }) => {
  const state = await fixture(page, { library: true }); state.copyAckLost = true;
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  const panel = await openWorkbenchLibrary(page);
  await panel.getByRole('button', { name: 'Добавить asset.zip в IDE', exact: true }).click();
  const form = panel.getByTestId('ide-library-copy');
  await form.getByRole('button', { name: 'Добавить в IDE', exact: true }).click();
  await expect(form.getByRole('alert')).toContainText('Копирование не подтверждено');
  await expect(form).not.toContainText('PRIVATE');
  await expect(form.getByLabel('Путь назначения')).toHaveAttribute('readonly');
  await expect(form.getByRole('button', { name: 'Добавить в IDE', exact: true })).toBeDisabled();
  expect(state.libraryCopies).toHaveLength(1);
});

test('Library upload persists a file without importing it into IDE or the legacy workspace', async ({ page }) => {
  const state = await fixture(page, { library: true });
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  const panel = await openWorkbenchLibrary(page);
  await panel.getByTestId('work-upload-input').setInputFiles({ name: 'upload.txt', mimeType: 'text/plain', buffer: Buffer.from('library only') });
  await expect(panel.getByText('upload.txt', { exact: true }).first()).toBeVisible();
  await expect.poll(() => state.libraryUploads.length).toBe(1);
  expect(state.libraryCopies).toEqual([]);
  expect(state.mutations.filter(path => !path.endsWith('/work/library/upload'))).toEqual([]);
  expect(state.agentMessages).toEqual([]);
});

test('agent suggestions preserve the shared draft and cancelling preparation never enqueues', async ({ page }, testInfo) => {
  if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1665, height: 945 });
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await selectFile(page);
  const narrow = page.viewportSize().width < 1100;
  if (narrow) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const pane = page.getByTestId('ide-agent-pane');
  await expect(pane).toBeVisible();
  await expect(pane.getByRole('heading', { name: 'Агент', exact: true })).toBeVisible();
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await pane.getByRole('button', { name: 'Добавь README с инструкцией запуска' }).click();
  await expect(input).toHaveValue('Добавь README с инструкцией запуска');
  expect(state.agentMessages).toEqual([]);
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await expect(input).toHaveValue('Добавь README с инструкцией запуска');
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(input).toBeVisible();
  await expect(input).toHaveValue('Добавь README с инструкцией запуска');
  await page.screenshot({ path: testInfo.outputPath('ide-agent-input.png'), animations: 'disabled' });
  await input.fill('Добавь инструкцию запуска');
  state.targetGate = deferred();
  await pane.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect(pane.getByText('Проверяю репозиторий перед отправкой…')).toBeVisible();
  await pane.getByRole('button', { name: 'Отменить', exact: true }).click();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue('Добавь инструкцию запуска');
  const cancelledGate = state.targetGate; state.targetGate = null; cancelledGate.resolve();
  expect(state.agentMessages).toEqual([]);
});

test('agent rail owns the shared input, bounded trace and scoped repository reply', async ({ page }, testInfo) => {
  if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1665, height: 945 });
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await selectFile(page);
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const pane = page.getByTestId('ide-agent-pane');
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Добавь инструкцию запуска');
  await pane.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => state.agentMessages.length).toBe(1);
  expect(state.agentMessages[0]).toMatchObject({ ide_target_id: '30000000-0000-0000-0000-000000000001', route_override: 'general' });
  expect(state.agentMessages[0]).not.toHaveProperty('workspace_ref');
  expect(state.agentMessages[0]).not.toHaveProperty('ide_context');
  await expect(input).toBeHidden();
  await expect(pane.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  const activity = pane.getByRole('region', { name: 'Выполнение запроса IDE' });
  const before = await activity.boundingBox();
  await page.screenshot({ path: testInfo.outputPath('ide-agent-running.png'), animations: 'disabled' });
  await state.socket.send(JSON.stringify({ type: 'agent_reply', reply: 'Полный ответ агента с подробным объяснением и кодом.', metadata: { ide_repository: A, ide_files_written: 1, ide_write_unconfirmed: false, ide_summary: 'Инструкция подготовлена.' } }));
  await expect(input).toBeVisible();
  await expect(pane.getByText('Инструкция подготовлена.', { exact: true })).toBeVisible();
  await expect(pane.getByText('Полный ответ агента с подробным объяснением и кодом.', { exact: true })).toHaveCount(0);
  await expect(pane.getByText('Подтверждено записей в среду: 1. Это не Git-коммит.')).toBeVisible();
  expect(before.height).toBeGreaterThan(150);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[data-testid="ide-agent-pane"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('ide-agent-result.png'), animations: 'disabled' });
  await pane.getByRole('button', { name: 'Открыть в Чате', exact: true }).click();
  await expect(page.getByText('Полный ответ агента с подробным объяснением и кодом.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(pane.getByTestId('ide-agent-summary')).toHaveText('Инструкция подготовлена.');
  await expect(input).toBeVisible();
});

test('inaccessible previous-account thread starts IDE on a fresh owned scope', async ({ page }) => {
  await fixture(page, { deniedThread: true });
  await expect(page).toHaveURL(/\/chat\/[a-f0-9-]{36}\?surface=work$/);
  expect(new URL(page.url()).pathname).not.toBe(`/chat/${THREAD}`);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await expect(page.getByText('Не удалось загрузить IDE', { exact: true })).toHaveCount(0);
});

test('semantic no-write result stays next to collapsed stages without a blank trace slot', async ({ page }, testInfo) => {
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await selectFile(page);
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Агент', exact: true }).click();
  const pane = page.getByTestId('ide-agent-pane');
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Объясни структуру');
  await pane.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => state.agentMessages.length).toBe(1);
  await expect(pane.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  const summary = 'В проекте пока нет файлов. Какую структуру создать: src, tests и docs или другую?';
  await state.socket.send(JSON.stringify({ type: 'agent_reply', reply: 'Подробный ответ.', metadata: { ide_repository: A, ide_files_written: 0, ide_summary: summary } }));
  await expect(pane.getByTestId('ide-agent-summary')).toHaveText(summary);
  await expect(pane.getByText('Подтверждённых записей в файлы нет.', { exact: true })).toHaveCount(0);
  const stages = pane.getByRole('button', { name: 'Этапы', exact: true });
  const result = pane.getByTestId('ide-agent-result');
  const before = await result.boundingBox();
  await stages.click();
  await expect(pane.getByRole('button', { name: 'Скрыть этапы', exact: true })).toBeVisible();
  await pane.getByRole('button', { name: /Ход работы/ }).click();
  await expect(stages).toHaveAttribute('aria-expanded', 'false');
  expect(Math.abs((await result.boundingBox()).y - before.y)).toBeLessThan(2);
  await page.screenshot({ path: testInfo.outputPath('ide-semantic-result.png'), animations: 'disabled' });
});

test('IDE code-agent and tree-code splits resize independently without losing input', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'Desktop-only split geometry; mobile uses explicit areas.');
  await page.setViewportSize({ width: 1665, height: 945 });
  await fixture(page);
  await selectFile(page);
  const pane = page.getByTestId('ide-agent-pane');
  const panels = page.getByTestId('ide-workbench-panels');
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Сохранённый ввод');
  expect(Math.abs((await pane.boundingBox()).width - ((await panels.boundingBox()).width - 6) / 2)).toBeLessThan(3);
  const split = page.getByRole('separator', { name: 'Ширина кода и агента' });
  const treeSplit = page.getByRole('separator', { name: 'Ширина дерева файлов и кода' });
  await treeSplit.focus(); await treeSplit.press('ArrowRight');
  await expect(treeSplit).toHaveAttribute('aria-valuenow', '32');
  await expect(split).toHaveAttribute('aria-valuenow', '50');
  const rect = await split.boundingBox();
  await page.mouse.move(rect.x + 3, rect.y + 50); await page.mouse.down();
  await page.mouse.move(rect.x - 100, rect.y + 50); await page.mouse.up();
  expect(Number(await split.getAttribute('aria-valuenow'))).toBeLessThan(50);
  await expect(treeSplit).toHaveAttribute('aria-valuenow', '32');
  await expect(input).toHaveValue('Сохранённый ввод');
  const files = page.getByRole('complementary', { name: 'Файлы репозитория', exact: true });
  const move = files.getByRole('button', { name: 'Переместить', exact: true });
  const caption = move.getByText('Переместить', { exact: true });
  await treeSplit.press('Home');
  await expect(treeSplit).toHaveAttribute('aria-valuenow', '20');
  await expect(caption).toBeHidden();
  const fileBounds = await files.boundingBox();
  const moveBounds = await move.boundingBox();
  const headingBounds = await files.getByRole('heading', { name: 'Репозиторий', exact: true }).boundingBox();
  expect(headingBounds.x + headingBounds.width).toBeLessThanOrEqual(moveBounds.x);
  expect(moveBounds.x + moveBounds.width).toBeLessThanOrEqual(fileBounds.x + fileBounds.width);
  await move.focus();
  await expect(page.getByRole('tooltip', { name: 'Переместить файл или папку', exact: true })).toBeVisible();
  await move.press('Enter');
  await expect(page.getByRole('dialog', { name: 'Переместить файл', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(move).toBeFocused();
  await split.focus(); await split.press('End');
  await treeSplit.focus(); await treeSplit.press('End');
  expect((await files.boundingBox()).width).toBeGreaterThanOrEqual(360);
  await expect(caption).toBeVisible();
  await expect(input).toHaveValue('Сохранённый ввод');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('ide-resized-panels.png'), animations: 'disabled' });
  await page.setViewportSize({ width: 393, height: 851 });
  await page.getByRole('button', { name: 'Агент', exact: true }).click();
  await expect(input).toHaveValue('Сохранённый ввод');
  await expect(page.getByRole('separator', { name: 'Ширина кода и агента' })).toHaveCount(0);
});

test('Markdown source switches to a safe formatted preview and back without writes', async ({ page }, testInfo) => {
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  state.entries.push({ path: 'README.md', type: 'file', size: 300, incomplete: false });
  state.files.set('README.md', '# Проект\n\n[К запуску](#запуск)\n\n- Исходники\n- Тесты\n\n| Имя | Роль |\n| --- | --- |\n| src | Код |\n\n[Исходник](src/main.py)\n\n![Трекер](https://example.test/track.png)\n\n<script>alert(1)</script>\n\n## Запуск\n\npython main.py');
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const file = page.getByRole('button', { name: 'README.md', exact: true });
  await expect(file).toBeVisible(); await file.click();
  const toggle = page.getByRole('group', { name: 'Вид Markdown' });
  await toggle.getByRole('button', { name: 'Превью', exact: true }).click();
  const preview = page.getByRole('region', { name: 'Превью Markdown README.md', exact: true });
  await expect(preview.getByRole('heading', { name: 'Проект', exact: true })).toBeVisible();
  await expect(preview.getByRole('table')).toContainText('src');
  await expect(preview.getByRole('list')).toContainText('Тесты');
  expect(await preview.locator('script,img').count()).toBe(0);
  const before = page.url();
  await preview.getByRole('link', { name: 'К запуску', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(preview.getByRole('heading', { name: 'Запуск', exact: true })).toBeFocused();
  expect(page.url()).toBe(before);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[aria-label="Превью Markdown README.md"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('ide-markdown-preview.png'), animations: 'disabled' });
  await toggle.getByRole('button', { name: 'Код', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Код файла README.md', exact: true })).toContainText('# Проект');
  await toggle.getByRole('button', { name: 'Превью', exact: true }).click();
  await preview.getByRole('link', { name: 'Исходник', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Код файла src/main.py', exact: true })).toBeVisible();
  expect(state.fileWrites).toEqual([]);
  expect(state.agentMessages).toEqual([]);
});

test('tree drag-and-drop moves files and folders with root and keyboard alternatives', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const state = await fixture(page);
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  state.entries.push({ path: 'docs', type: 'dir', size: 0, incomplete: false }, { path: 'main.py', type: 'file', size: 13, incomplete: false });
  state.files.set('main.py', 'print("drag")');
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const tree = page.getByRole('region', { name: 'Дерево репозитория', exact: true });
  const node = path => tree.getByRole('button', { name: path, exact: true });
  await node('main.py').click();
  await expect(page.getByRole('region', { name: 'Код файла main.py', exact: true })).toContainText('print("drag")');
  await node('main.py').dragTo(node('docs'));
  await expect.poll(() => state.fileMoves?.length).toBe(1);
  await expect(page.getByRole('region', { name: 'Код файла docs/main.py', exact: true })).toContainText('print("drag")');
  await node('src').dragTo(node('docs'));
  await expect(node('docs/src')).toBeVisible();
  expect(state.entries.some(item => item.path === 'docs/src/main.py')).toBe(true);
  await node('docs/src').focus();
  await page.getByRole('button', { name: 'Переместить', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Переместить папку' });
  await dialog.getByRole('combobox', { name: 'Папка назначения' }).press('ArrowDown');
  await page.getByRole('option', { name: 'Корень репозитория', exact: true }).click();
  await dialog.getByRole('button', { name: 'Переместить', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(node('src')).toBeVisible();
  const bounds = await tree.boundingBox();
  await node('docs/main.py').dragTo(tree, { targetPosition: { x: bounds.width / 2, y: bounds.height - 24 } });
  await expect(node('main.py')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Код файла main.py', exact: true })).toContainText('print("drag")');
  expect(state.files.get('main.py')).toBe('print("drag")');
  state.failMove = true;
  await node('main.py').dragTo(node('docs'));
  await expect(page.getByRole('alert').filter({ hasText: 'Перемещение не подтверждено' })).toBeVisible();
  await expect(node('main.py')).toBeVisible();
  expect(state.entries.some(item => item.path === 'docs/main.py')).toBe(false);
  expect(state.agentMessages).toEqual([]);
  await page.screenshot({ path: info.outputPath('ide-tree-drag-move.png') });
});

test('create, edit and move retain contents, tabs and a recoverable destination on failure', async ({ page }) => {
  const state = await fixture(page);
  const create = page.getByRole('button', { name: 'Создать файл', exact: true }).first();
  await expect(create).toBeEnabled(); await create.click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Путь в репозитории').fill('new.py');
  await dialog.getByRole('button', { name: 'Создать', exact: true }).click();
  await expect(dialog).toBeHidden();
  const input = page.getByRole('textbox', { name: 'Содержимое new.py', exact: true });
  await input.fill('print(1)');
  await page.getByRole('button', { name: 'Записать в среду', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Записать в среду', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Переместить', exact: true }).click();
  dialog = page.getByRole('dialog');
  const folder = dialog.getByRole('combobox', { name: 'Папка назначения' });
  await folder.focus(); await folder.press('ArrowDown');
  await page.getByRole('option', { name: 'src', exact: true }).click();
  await page.addScriptTag({ content: axe.source });
  expect((await page.evaluate(() => window.axe.run(document.querySelector('[role="dialog"]'), { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa'] }))).violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  state.failMove = true;
  await dialog.getByRole('button', { name: 'Переместить', exact: true }).click();
  await expect(dialog.getByText('Перемещение не подтверждено. Обновите дерево перед повтором.')).toBeVisible();
  await expect(dialog.getByLabel('Имя файла')).toHaveValue('new.py');
  expect(state.files.get('new.py')).toBe('print(1)');
  state.failMove = false;
  await dialog.getByRole('button', { name: 'Переместить', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('button', { name: 'Показать src/new.py', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Показать new.py', exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Код файла src/new.py', exact: true })).toContainText('print(1)');
  expect(state.files.has('new.py')).toBe(false);
  expect(state.files.get('src/new.py')).toBe('print(1)');
});

for (const lostAck of [false, true]) test(`nonempty clone preserves the original and selects a separate project (lost ACK: ${lostAck})`, async ({ page }) => {
  const state = await fixture(page);
  await expect(page.getByRole('button', { name: 'Клонировать по ссылке', exact: true })).toBeEnabled();
  state.cloneConflict = true; state.cloneAckLost = lostAck; state.cloneGate = deferred();
  await page.getByRole('button', { name: 'Клонировать по ссылке', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Ссылка на репозиторий').fill('https://github.com/owner/repository');
  await dialog.getByRole('button', { name: 'Клонировать', exact: true }).click();
  await expect.poll(() => state.isolatedClones?.length).toBe(1);
  await expect(dialog.getByLabel('Ссылка на репозиторий')).toHaveAttribute('readonly');
  expect(state.isolatedClones[0]).toMatchObject({ source_repository_id: A, origin: 'https://github.com/owner/repository' });
  state.cloneGate.resolve();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('Клон проекта', { exact: true }).first()).toBeVisible();
  expect(state.preparations.at(-1)).toEqual({ repository_id: C });
  expect(state.currentCloneCalls).toBe(1);
  expect(state.isolatedClones).toHaveLength(1);
  await page.getByRole('combobox', { name: 'Репозиторий IDE' }).focus();
  await page.getByRole('combobox', { name: 'Репозиторий IDE' }).press('ArrowDown');
  await page.getByRole('option', { name: names[0], exact: true }).click();
  await selectFile(page);
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toContainText('Проект A');
  expect(state.agentMessages).toEqual([]);
});

test('reload restores a reserved clone destination and resumes only its original intent', async ({ page }, testInfo) => {
  const attempt = { intent_id: '30000000-0000-0000-0000-000000000002', source_repository_id: B,
    repository: { repository_id: A, name: names[0], state: 'registered' }, state: 'preparing',
    request: { origin: 'https://github.com/owner/repository.git', branch: 'main' } };
  const state = await fixture(page, { recoveredAttempt: attempt });
  const bar = page.getByTestId('ide-clone-recovery');
  await page.getByRole('button', { name: 'Состояние IDE', exact: true }).click();
  await expect(bar.getByRole('button', { name: 'Продолжить…', exact: true })).toBeEnabled();
  expect(state.isolatedClones?.length || 0).toBe(0);
  await page.reload();
  await page.getByRole('button', { name: 'Состояние IDE', exact: true }).click();
  await expect(bar.getByRole('button', { name: 'Продолжить…', exact: true })).toBeEnabled();
  expect(state.isolatedClones?.length || 0).toBe(0);
  await bar.getByRole('button', { name: 'Продолжить…', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Ссылка на репозиторий')).toHaveValue(attempt.request.origin);
  await expect(dialog.getByLabel('Ссылка на репозиторий')).toHaveAttribute('readonly');
  await expect(dialog.getByLabel('Ветка (необязательно)')).toHaveValue('main');
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[role="dialog"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('ide-clone-restored-dialog.png') });
  await dialog.getByRole('button', { name: 'Продолжить попытку', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: 'Состояние IDE', exact: true }).click();
  await expect(bar).toContainText('Клонирование завершено');
  await expect(page.getByRole('button', { name: 'Создать файл', exact: true }).first()).toBeEnabled();
  expect(state.isolatedClones).toEqual([{ intent_id: attempt.intent_id, source_repository_id: B, ...attempt.request }]);
  expect(state.currentCloneCalls || 0).toBe(0);
  expect(state.descriptorsCreated).toBe(0);
  expect(state.agentMessages).toEqual([]);
});

test('failed recovery lookup is not permission to create another clone', async ({ page }) => {
  const state = await fixture(page, { failRecovery: true });
  await page.getByRole('button', { name: 'Состояние IDE', exact: true }).click();
  const bar = page.getByTestId('ide-clone-recovery');
  await expect(bar.getByRole('alert')).toContainText('Не удалось проверить прежнее клонирование');
  await expect(page.getByRole('button', { name: 'Клонировать по ссылке', exact: true })).toBeDisabled();
  expect(state.isolatedClones?.length || 0).toBe(0);
  state.failRecovery = false;
  await bar.getByRole('button', { name: 'Проверить клонирование', exact: true }).click();
  await expect(bar).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Клонировать по ссылке', exact: true })).toBeEnabled();
  expect(state.isolatedClones?.length || 0).toBe(0);
  expect(await page.getByTestId('ide-studio').innerText()).not.toContain('PRIVATE_CLONE_RECOVERY');
});

test('repository selection, passive tree, compact controls, code and keyboard popup', async ({ page }, testInfo) => {
  const state = await fixture(page);
  await expect(page).toHaveTitle(/IDE/);
  const select = page.getByRole('combobox', { name: 'Репозиторий IDE' });
  await expect(select).toBeEnabled();
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  expect(state.reads.some((path) => path.endsWith('/files/read'))).toBe(false);
  await selectFile(page);
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toContainText('Проект A');
  const mobile = page.viewportSize().width < 768;
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Файлы', exact: true }).click();
  await page.getByRole('button', { name: 'src/вложенная-папка-с-длинным-именем', exact: true }).click();
  await expect(page.getByText('Содержимое загружено не полностью')).toBeVisible();
  await select.focus(); await select.press('ArrowDown');
  const menu = page.getByRole('listbox');
  await expect(menu).toBeVisible();
  const geometry = await page.evaluate(() => {
    const list = document.querySelector('[role="listbox"]').parentElement.getBoundingClientRect();
    const control = document.querySelector('[aria-label="Репозиторий IDE"][role="combobox"]').closest('[class*="control"]').getBoundingClientRect();
    return { list: list.width, control: control.width, left: Math.abs(list.left - control.left) };
  });
  expect(Math.abs(geometry.list - geometry.control)).toBeLessThanOrEqual(1);
  expect(geometry.left).toBeLessThanOrEqual(1);
  await page.getByRole('option', { name: names[1], exact: true }).click();
  await expect(menu).toHaveCount(0);
  await selectFile(page);
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toContainText('Проект B');
  expect(state.mutations).toEqual([]);
  expect(state.legacyReads).toBe(0);
  const refresh = await page.getByRole('button', { name: 'Обновить IDE', exact: true }).boundingBox();
  expect(refresh.height).toBe(mobile ? 30 : 34);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(async () => window.axe.run(document.querySelector('[data-testid="ide-studio"]')));
  expect(audit.violations.filter((item) => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('ide-read-scene.png'), fullPage: true });
});

test('slow registry and failure never offer creation or show a false empty directory', async ({ page }) => {
  const gate = deferred();
  const loading = fixture(page, { listGate: gate.promise, empty: true });
  await expect(page.getByText('Загружаю IDE…')).toBeVisible();
  await expect(page.getByText('Каталог пока пуст.')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /создать/i })).toHaveCount(0);
  gate.resolve(); const state = await loading;
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  expect(state.preparations).toEqual([{}]);
  expect(state.mutations).toEqual([]);
});

test('pending allocation automatically completes Git setup once after a ready observation', async ({ page }) => {
  const state = await fixture(page, { empty: true, preparePending: true });
  await expect(page.getByText('Среда запускается', { exact: true })).toBeVisible();
  expect(state.preparations).toEqual([{}]);
  await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Запустить среду', exact: true })).toHaveCount(0);
  state.continuationGate = deferred();
  state.runtimeState = 'ready';
  await expect.poll(() => state.preparations).toEqual([{}, { repository_id: A }]);
  await expect(page.getByText('Подготавливаю проект и среду IDE…', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать файл', exact: true })).toHaveCount(0);
  state.continuationGate.resolve();
  await expect(page.getByTitle('Git · main', { exact: true })).toHaveText('main');
  await expect(page.getByRole('button', { name: 'Создать файл', exact: true }).first()).toBeEnabled();
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(page.getByTitle('Git · main', { exact: true })).toHaveText('main');
  expect(state.preparations).toEqual([{}, { repository_id: A }]);
  expect(state.descriptorsCreated).toBe(1);
  expect(state.mutations).toEqual([]);
  expect(state.agentMessages).toEqual([]);
});

test('leaving during deferred setup cannot strand IDE in loading on return', async ({ page }) => {
  const state = await fixture(page, { empty: true, preparePending: true });
  await expect(page.getByText('Среда запускается', { exact: true })).toBeVisible();
  const gate = deferred();
  state.continuationGate = gate; state.runtimeState = 'ready';
  await expect.poll(() => state.preparations.length).toBe(2);
  await expect(page.getByText('Подготавливаю проект и среду IDE…', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  state.continuationGate = null;
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(page.getByTitle('Git · main', { exact: true })).toHaveText('main');
  await expect(page.getByRole('button', { name: 'Создать файл', exact: true }).first()).toBeEnabled();
  gate.resolve();
  expect(state.preparations).toEqual([{}, { repository_id: A }, { repository_id: A }]);
  expect(state.descriptorsCreated).toBe(1);
  expect(state.agentMessages).toEqual([]);
  expect(state.mutations).toEqual([]);
});

test('read failure retains file, expired runtime is not an empty tree, navigation keeps query', async ({ page }) => {
  const state = await fixture(page);
  await selectFile(page);
  state.failFile = true;
  await page.getByRole('button', { name: 'Обновить файл', exact: true }).click();
  const notices = page.getByRole('button', { name: 'Состояние IDE', exact: true });
  await expect(notices).toHaveAttribute('title', /[1-9]\d* уведомлений/);
  await notices.click();
  await expect(page.getByText('Не удалось открыть файл', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Закрыть состояние IDE', exact: true }).click();
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Код', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toContainText('Проект A');
  await expect(page.getByTestId('ide-studio')).not.toContainText('PRIVATE_BODY');
  state.runtimeState = 'expired';
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  await expect(page.getByText('Срок среды истёк', { exact: true })).toBeVisible();
  await expect(page.getByText('Каталог пока пуст.')).toHaveCount(0);
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}\\?keep=1$`));
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(page).toHaveURL(/keep=1&surface=work/);
  expect(state.mutations).toEqual([]);
});

test('runtime status uses the project toolbar instead of duplicate full-width information rows', async ({ page }, info) => {
  const state = await fixture(page);
  const toolbar = page.getByRole('region', { name: 'Репозиторий IDE', exact: true });
  const ready = page.getByRole('button', { name: 'Состояние среды: Среда доступна', exact: true });
  await expect(ready).toBeVisible();
  await expect(toolbar).toContainText('Среда доступна');
  await expect(page.getByText('Отдельная временная среда', { exact: true })).toHaveCount(0);
  const count = state.preparations.length;
  await ready.click();
  await expect(page.getByText(/Запись в среду не является/)).toBeVisible();
  await page.getByRole('button', { name: 'Закрыть сведения о среде' }).click();
  state.runtimeState = 'expired';
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const expired = page.getByRole('button', { name: 'Состояние среды: Срок среды истёк', exact: true });
  await expect(expired).toBeVisible();
  await expect(toolbar).toContainText('Срок среды истёк');
  const details = page.getByText(/Временная среда завершена\. Сохранённый проект можно восстановить из истории\./);
  await expect(details).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('compact-expired-status.png'), animations: 'disabled' });
  await expired.click();
  await expect(details).toBeVisible();
  await expect(details).toContainText('Новая пустая среда автоматически не создаётся');
  expect(state.preparations).toHaveLength(count);
  expect(state.mutations).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(expired).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('IDE repository actions occupy one toolbar without a duplicate create action', async ({ page }, info) => {
  await page.setViewportSize({ width: 1665, height: 945 });
  await fixture(page);
  const toolbar = page.getByRole('region', { name: 'Репозиторий IDE', exact: true });
  const create = page.getByRole('button', { name: 'Создать файл', exact: true });
  await expect(create).toHaveCount(1);
  const clone = toolbar.getByRole('button', { name: 'Клонировать по ссылке', exact: true });
  await expect(clone).toBeEnabled();
  const bounds = await toolbar.boundingBox();
  const createBounds = await create.boundingBox();
  const cloneBounds = await clone.boundingBox();
  expect(bounds.height).toBeLessThan(64);
  expect(Math.abs(createBounds.y - cloneBounds.y)).toBeLessThan(2);
  await page.screenshot({ path: info.outputPath('ide-one-toolbar.png'), animations: 'disabled' });
});

test('registry failure is recoverable and never exposes transport bodies', async ({ page }) => {
  const state = await fixture(page, { failList: true });
  await expect(page.getByRole('alert')).toContainText('Не удалось получить список репозиториев');
  const retry = page.getByRole('button', { name: 'Повторить чтение', exact: true });
  await retry.focus(); await retry.press('Enter');
  await expect(retry).toBeVisible();
  await expect.poll(() => state.reads.length).toBe(2);
  await expect(page.getByText('В этом чате пока нет репозиториев IDE.')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить IDE' })).toBeVisible();
  state.failList = false;
  await retry.click();
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
});

test('narrow IDE keeps creation and clone actions within two toolbar rows', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await fixture(page);
  const toolbar = page.getByRole('region', { name: 'Репозиторий IDE', exact: true });
  await expect(toolbar.getByRole('button', { name: 'Клонировать по ссылке', exact: true })).toBeEnabled();
  const project = toolbar.getByRole('button', { name: 'Новый проект', exact: true });
  await expect(project).toBeEnabled();
  const bounds = await toolbar.boundingBox();
  expect(bounds.height).toBeLessThanOrEqual(100);
  expect((await project.boundingBox()).width).toBeLessThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('ide-320-toolbar.png'), animations: 'disabled' });
});

test('empty entry prepares one owned project and Git without manual create/start actions', async ({ page }, testInfo) => {
  const state = await fixture(page, { empty: true });
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Запустить среду', exact: true })).toHaveCount(0);
  await expect(page.getByTitle('Git · main', { exact: true })).toHaveText('main');
  expect(state.mutations).toEqual([]);
  expect(state.preparations).toEqual([{}]);
  expect(state.descriptorsCreated).toBe(1);
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(async () => window.axe.run(document.querySelector('[data-testid="ide-studio"]')));
  expect(audit.violations.filter((item) => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  const size = await page.getByRole('button', { name: 'Новый проект', exact: true }).boundingBox();
  expect(size.height).toBe(page.viewportSize().width < 768 ? 30 : 34);
  await page.screenshot({ path: testInfo.outputPath('ide-new-project.png'), animations: 'disabled' });
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  expect(state.preparations).toHaveLength(1);
  expect(state.descriptorsCreated).toBe(1);
  expect(state.mutations).toEqual([]);
  expect(state.legacyReads).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('slow preparation never exposes create/start controls and failed acknowledgement retries the same default', async ({ page }) => {
  const gate = deferred();
  const state = await fixture(page, { empty: true, prepareGate: gate.promise, failPrepare: true });
  await expect(page.getByText('Подготавливаю проект и среду IDE…')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Запустить среду', exact: true })).toHaveCount(0);
  gate.resolve();
  await expect(page.getByRole('heading', { name: 'Не удалось подготовить IDE' })).toBeVisible();
  await expect(page.getByTestId('ide-studio')).not.toContainText('PRIVATE_PREPARATION');
  expect(state.preparations).toEqual([{}]);
  state.failPrepare = false;
  const retry = page.getByRole('button', { name: 'Повторить подготовку', exact: true });
  await retry.focus(); await retry.press('Enter');
  await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
  expect(state.preparations).toEqual([{}, {}]);
  expect(state.descriptorsCreated).toBe(1);
  expect(state.agentMessages).toEqual([]);
});

test('file tabs cache reads, close with keyboard focus, and stay in the current repository', async ({ page }, testInfo) => {
  const state = await fixture(page);
  await selectFile(page);
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' }).locator('.token').first()).toBeVisible();
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Файлы', exact: true }).click();
  await page.getByRole('button', { name: 'src/helpers.py', exact: true }).click();
  const navigation = page.getByRole('navigation', { name: 'Открытые файлы' });
  const main = navigation.getByRole('button', { name: 'Показать src/main.py', exact: true });
  await expect(main).toBeVisible();
  await expect(navigation.getByRole('button', { name: 'Показать src/helpers.py', exact: true })).toHaveAttribute('aria-current', 'page');
  const readCount = state.reads.filter((path) => path.endsWith('/files/read')).length;
  await main.focus(); await main.press('Enter');
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toBeVisible();
  expect(state.reads.filter((path) => path.endsWith('/files/read'))).toHaveLength(readCount);
  await page.screenshot({ path: testInfo.outputPath('ide-code-tabs.png'), fullPage: true });
  const close = navigation.getByRole('button', { name: 'Закрыть src/main.py', exact: true });
  await close.focus(); await close.press('Enter');
  await expect(main).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Просмотр исходника', exact: true })).toBeFocused();
  await expect(page.getByRole('region', { name: 'Код файла src/helpers.py' })).toBeVisible();
  const selector = page.getByRole('combobox', { name: 'Репозиторий IDE' });
  await selector.locator('xpath=ancestor::*[contains(@class,"-control")]').click();
  await page.getByRole('option', { name: names[1], exact: true }).click();
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Код', exact: true }).click();
  await expect(navigation.getByRole('button')).toHaveCount(0);
  expect(state.mutations).toEqual([]);
  expect(state.legacyReads).toBe(0);
});

test('reflow proxy and reduced motion keep code and pane controls reachable', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 600 });
  await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' });
  const state = await fixture(page);
  await selectFile(page);
  await page.getByRole('button', { name: 'Файлы', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Дерево репозитория', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Код', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Код файла src/main.py' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(state.mutations).toEqual([]);
});

test('history opened from recovery returns focus to its own opener', async ({ page }) => {
  const state = await fixture(page, { savedProjects: true });
  await page.getByRole('button', { name: 'Сохранить проект', exact: true }).click();
  await expect.poll(() => state.saves?.length).toBe(1);
  state.runtimeState = 'expired';
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const recovery = page.getByRole('region', { name: 'Восстановление проекта', exact: true });
  const opener = recovery.getByRole('button', { name: 'Открыть историю', exact: true });
  await opener.click();
  await expect(page.getByRole('dialog', { name: /История проекта/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(opener).toBeFocused();
  expect(state.restores || []).toEqual([]);
});

test('saved project history is compact, keyboard reachable and restores only after expiry', async ({ page }, info) => {
  const state = await fixture(page, { savedProjects: true });
  const save = page.getByRole('button', { name: 'Сохранить проект', exact: true });
  await expect(save).toBeEnabled(); await save.focus(); await save.press('Enter');
  await expect.poll(() => state.saves?.length).toBe(1);
  await page.getByRole('button', { name: 'История проекта', exact: true }).click();
  const modal = page.getByRole('dialog', { name: /История проекта/ });
  await expect(modal.getByRole('listitem').getByText(/Последний снимок/)).toBeVisible();
  await expect(modal.getByRole('button', { name: 'Восстановить', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'История проекта', exact: true })).toBeFocused();
  state.runtimeState = 'expired';
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const recovery = page.getByRole('region', { name: 'Восстановление проекта', exact: true });
  await expect(recovery.getByRole('heading', { name: 'Среда завершена' })).toBeVisible();
  await expect(save).toBeDisabled();
  const preparations = state.preparations.length;
  await page.screenshot({ path: info.outputPath('ide-expired-recovery-desktop.png') });
  await page.setViewportSize({ width: 320, height: 740 });
  await expect(recovery.getByRole('button', { name: 'Открыть историю' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.addScriptTag({ content: axe.source });
  const recoveryAudit = await page.evaluate(() => window.axe.run(document.querySelector('[aria-label="Восстановление проекта"]')));
  expect(recoveryAudit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  await page.screenshot({ path: info.outputPath('ide-expired-recovery-320.png') });
  expect(state.preparations).toHaveLength(preparations);
  expect(state.restores || []).toEqual([]);
  await recovery.getByRole('button', { name: 'Открыть историю' }).click();
  await modal.getByRole('button', { name: 'Восстановить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Отмена', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Восстановить', exact: true }).click();
  await expect.poll(() => state.restores?.length).toBe(1);
  await expect(page.getByRole('dialog').getByText('Проект восстановлен.', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(recovery).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'История проекта', exact: true })).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('button', { name: 'История проекта', exact: true }).click();
  await page.screenshot({ path: info.outputPath('ide-saved-project-history.png') });
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 320, height: 740 });
  await expect(save).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'История проекта', exact: true }).click();
  const bounds = await page.getByRole('dialog').boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0); expect(bounds.x + bounds.width).toBeLessThanOrEqual(320);
  await page.screenshot({ path: info.outputPath('ide-saved-project-history-320.png') });
  expect(state.agentMessages).toEqual([]);
});

test('expired project without saved versions uses only the toolbar create action', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const state = await fixture(page, { savedProjects: true });
  await expect(page.getByRole('button', { name: 'Сохранить проект', exact: true })).toBeEnabled();
  const preparations = state.preparations.length;
  state.runtimeState = 'expired';
  await page.getByRole('button', { name: 'Обновить IDE', exact: true }).click();
  const recovery = page.getByRole('region', { name: 'Восстановление проекта', exact: true });
  await expect(recovery).toContainText('Сохранённых версий нет.');
  expect(state.preparations).toHaveLength(preparations);
  expect(state.restores || []).toEqual([]);
  await expect(recovery.getByRole('button', { name: 'Новый проект', exact: true })).toHaveCount(0);
  const newProject = page.getByRole('button', { name: 'Новый проект', exact: true });
  await expect(newProject).toHaveCount(1);
  await page.screenshot({ path: info.outputPath('ide-expired-no-versions-320.png') });
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(newProject).toHaveCount(1);
  await expect(recovery).not.toContainText('Можно начать отдельный');
  await page.screenshot({ path: info.outputPath('ide-expired-no-versions-desktop.png') });
  await page.setViewportSize({ width: 320, height: 740 });
  await newProject.focus();
  await newProject.press('Enter');
  await expect(page.getByRole('textbox', { name: 'Название проекта', exact: true })).toBeVisible();
  expect(state.descriptorsCreated).toBe(0);
  expect(state.mutations).toEqual([]);
  expect(state.agentMessages).toEqual([]);
});

test('new IDE project keeps one create identity after lost acknowledgement and surface switch', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const state = await fixture(page);
  await expect(page.getByRole('button', { name: 'Обновить IDE', exact: true })).toBeEnabled();
  const creates = [];
  await page.route(`**/api/chats/${THREAD}/ide/repositories`, async route => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    const payload = route.request().postDataJSON(); creates.push(payload);
    if (creates.length === 1) { await route.abort(); return; }
    await route.fulfill({ json: { repository_id: A, name: payload.name, state: 'registered' } });
  });
  await page.getByRole('button', { name: 'Новый проект', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Название проекта', exact: true });
  await expect(input).toBeFocused();
  await expect(page.getByText('В этом чате пока нет репозиториев IDE.', { exact: true })).toHaveCount(0);
  await input.fill('Новый рабочий проект');
  await page.getByRole('button', { name: 'Создать проект', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Повтор использует тот же запрос');
  await expect(input).toHaveAttribute('readonly', '');
  expect(creates).toHaveLength(1);
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await expect(input).toHaveValue('Новый рабочий проект');
  await expect(input).toHaveAttribute('readonly', '');
  expect(creates).toHaveLength(1);
  await page.screenshot({ path: info.outputPath('ide-new-project-retry-320.png') });
  await page.addScriptTag({ content: axe.source });
  const audit = await page.evaluate(() => window.axe.run(document.querySelector('[data-testid="ide-studio"]')));
  expect(audit.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);
  await page.getByRole('button', { name: 'Повторить создание', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Название проекта', exact: true })).toHaveCount(0);
  expect(creates).toHaveLength(2); expect(creates[1]).toEqual(creates[0]);
  expect(state.agentMessages).toEqual([]); expect(state.fileWrites).toEqual([]);
});

test('unsettled snapshot stays protected; safe cleanup is explicit and preserves project files', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const state = await fixture(page, { savedProjects: true });
  await expect(page.getByRole('button', { name: 'Сохранить проект', exact: true })).toBeEnabled();
  const pending = { checkpoint_id: '50000000-0000-4000-8000-000000000001', state: 'pending', is_current: false,
    size_bytes: 2048, created_at: '2026-10-18T17:00:00Z', can_discard: false };
  state.savedVersions = [pending]; state.checkpointStatus = { ...pending, collected: false }; state.unreadableCheckpoint = true;
  await page.getByRole('button', { name: 'История проекта', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: /История проекта/ });
  await dialog.getByRole('button', { name: 'Проверить', exact: true }).click();
  await expect(dialog.getByText(/Завершение загрузки не подтверждено/)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Удалить незавершённый снимок', exact: true })).toHaveCount(0);
  state.checkpointStatus.can_discard = true;
  await dialog.getByRole('button', { name: 'Проверить', exact: true }).click();
  const remove = dialog.getByRole('button', { name: 'Удалить незавершённый снимок', exact: true });
  await expect(remove).toBeEnabled(); await remove.click();
  await expect(page.getByRole('button', { name: 'Отмена', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Отмена', exact: true }).click();
  await expect(remove).toBeFocused(); expect(state.discards).toEqual([]);
  await remove.press('Enter'); state.discardGate = deferred();
  await page.getByRole('button', { name: 'Удалить снимок', exact: true }).click();
  await expect(page.getByText('Удаляю незавершённый снимок…', { exact: true })).toBeVisible();
  state.discardGate.resolve();
  await expect(dialog.getByText('Незавершённый снимок удалён. Файлы проекта не изменены.', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Закрыть историю проекта', exact: true })).toBeFocused();
  await expect(dialog.getByText(/Восстановление доступно после завершения/)).toHaveCount(0);
  expect(state.discards).toHaveLength(1); expect(state.fileWrites).toEqual([]); expect(state.saves || []).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('ide-safe-cleanup-320.png') });
});

test('lost cleanup acknowledgement is checked without a second delete or new Save', async ({ page }) => {
  const state = await fixture(page, { savedProjects: true });
  await expect(page.getByRole('button', { name: 'Сохранить проект', exact: true })).toBeEnabled();
  const pending = { checkpoint_id: '50000000-0000-4000-8000-000000000001', state: 'retired', is_current: false,
    size_bytes: 2048, created_at: '2026-10-18T17:00:00Z', can_discard: true };
  state.savedVersions = [pending]; state.checkpointStatus = { ...pending, collected: false }; state.discardAckLost = true;
  await page.getByRole('button', { name: 'История проекта', exact: true }).click();
  await page.getByRole('button', { name: 'Удалить незавершённый снимок', exact: true }).click();
  await page.getByRole('button', { name: 'Удалить снимок', exact: true }).click();
  await expect(page.getByText(/Удаление не подтверждено/)).toBeVisible();
  await page.getByRole('button', { name: 'Проверить', exact: true }).click();
  await expect(page.getByText('Незавершённый снимок удалён. Файлы проекта не изменены.', { exact: true })).toBeVisible();
  expect(state.discards).toHaveLength(1); expect(state.fileWrites).toEqual([]); expect(state.saves || []).toEqual([]);
});

test('revoking an unknown upload unlocks a fresh Save without deletion or quota release', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const pending = { checkpoint_id: '50000000-0000-4000-8000-000000000001', state: 'pending', is_current: false,
    size_bytes: 2048, created_at: '2026-10-18T17:00:00Z', can_discard: false, can_abandon: true };
  await page.addInitScript(data => sessionStorage.setItem(data.key, JSON.stringify(data.intent)), {
    key: `gpthub.ide.pending:${THREAD}:${A}`,
    intent: { kind: 'save', checkpoint_id: pending.checkpoint_id, generation: GENERATION, base_checkpoint_id: null },
  });
  const state = await fixture(page, { savedProjects: true, pendingCheckpoint: pending });
  const save = page.getByRole('button', { name: 'Сохранить проект', exact: true });
  await expect(save).toBeDisabled();
  await page.getByRole('button', { name: 'История проекта', exact: true }).click();
  const abort = page.getByRole('button', { name: 'Отменить попытку сохранения', exact: true });
  await abort.click(); await expect(page.getByRole('button', { name: 'Отмена', exact: true })).toBeFocused();
  await page.keyboard.press('Escape'); await expect(abort).toBeFocused();
  expect(state.abandons || []).toEqual([]);
  await abort.press('Enter'); state.abandonGate = deferred();
  await page.getByRole('button', { name: 'Отменить попытку', exact: true }).click();
  await expect(page.getByText('Отменяю попытку сохранения…', { exact: true })).toBeVisible();
  state.abandonGate.resolve();
  await expect(page.getByText('Попытка отменена. Файлы проекта не изменены.', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog').getByText(/2 КБ из 1 ГБ/)).toBeVisible();
  expect(state.discards || []).toEqual([]); expect(state.abandons).toHaveLength(1);
  await page.screenshot({ path: info.outputPath('ide-abandon-320.png') });
  await page.keyboard.press('Escape'); await expect(save).toBeEnabled(); await save.click();
  await expect.poll(() => state.saves.length).toBe(1);
  expect(state.saves[0].checkpoint_id).not.toBe(pending.checkpoint_id);
  expect(state.fileWrites).toEqual([]); expect(state.agentMessages).toEqual([]);
});
