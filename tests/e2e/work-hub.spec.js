const { test, expect } = require('@playwright/test');
const { triggerWorkbenchLibrary, openWorkbenchLibrary } = require('./helpers/workbenchLibrary');
const axeCore = require('axe-core');
const { createServer } = require('http');

const THREAD_ID = 'work-hub-contract-thread';

function snapshot({ active, uploaded, librarySaved, documentReady, vendorAvailable, vendorApplied }) {
  const entries = [];
  if (uploaded) entries.push({ path: 'brief.txt', type: 'file', size: 18 });
  if (documentReady) {
    entries.push(
      { path: 'documents/paper/document.toml', type: 'file', size: 180 },
      { path: 'documents/paper/main.tex', type: 'file', size: 320 },
    );
  }
  const libraryItems = [];
  if (uploaded || librarySaved) {
    libraryItems.push({
      file_id: 'file-opaque-1', name: 'brief.txt', file_type: 'text/plain', availability: 'ready',
    });
  }
  if (vendorAvailable) {
    libraryItems.push({
      file_id: 'vendor-opaque-1', name: 'journal-kit.zip',
      file_type: 'application/zip', availability: 'ready',
    });
  }
  return {
    contract_version: 2,
    workspace: active
      ? {
        state: 'ready',
        revision: vendorApplied ? 'revision-3' : uploaded ? 'revision-2' : 'revision-1',
        recovered: false,
        entries,
        history: [],
      }
      : {
        state: 'absent',
        revision: '',
        recovered: false,
        entries: [],
        history: [],
      },
    room: {
      state: active ? 'ready' : 'absent',
      revision: active ? (uploaded ? 'revision-2' : 'revision-1') : '',
      issues: [],
      leases: [],
      activity: [],
      control: { state: 'running' },
    },
    library: {
      state: 'ready',
      items: libraryItems,
      next_cursor: null,
      next_offset: null,
    },
  };
}

async function installWorkApi(page) {
  const state = {
    active: false,
    uploaded: false,
    librarySaved: false,
    deferUpload: false,
    failCopy: false,
    uploadCalls: 0,
    copyCalls: 0,
    activationCalls: 0,
    leaseReleases: 0,
    fileContent: 'synthetic work contract',
    holdWrite: null,
    holdAcquire: null,
    acquireCalls: 0,
    writeCalls: 0,
    holdSnapshot: null,
    holdActivation: null,
    heldSnapshotCalls: 0,
    heldSnapshotFinished: 0,
    documentReady: false,
    documentBuild: null,
    vendorAvailable: false,
    vendorApplied: false,
    issueReads: 0,
    issueCreates: 0,
    failIssueRefresh: false,
  };
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', 'e2e-opaque-token');
  });
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === '/api/profile/me') {
      await route.fulfill({ json: { id: 'user-opaque-1', email: 'work@example.test', permissions: [] } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work` && method === 'GET') {
      const responseSnapshot = snapshot(state);
      const hold = state.holdSnapshot;
      if (hold) {
        state.heldSnapshotCalls += 1;
        await hold;
      }
      try {
        await route.fulfill({ json: responseSnapshot });
      } finally {
        if (hold) state.heldSnapshotFinished += 1;
      }
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work/activate` && method === 'POST') {
      state.activationCalls += 1;
      if (state.holdActivation) await state.holdActivation;
      state.active = true;
      await route.fulfill({ json: snapshot(state) });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work/upload` && method === 'POST') {
      state.uploadCalls += 1;
      state.librarySaved = true;
      state.active = !state.deferUpload;
      state.uploaded = !state.deferUpload;
      await route.fulfill({
        json: {
          outcome: state.deferUpload ? 'library_saved' : 'imported',
          workspace_status: state.deferUpload ? 'unavailable' : 'ready',
          revision: state.deferUpload ? '' : 'revision-2',
          file: {
            file_id: 'file-opaque-1',
            name: 'brief.txt',
            file_type: 'text/plain',
            availability: 'ready',
          },
        },
      });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work/library/file-opaque-1/copy` && method === 'POST') {
      state.copyCalls += 1;
      expect(request.postDataJSON()).toEqual({ expected_revision: 'revision-1', fence: 7 });
      state.uploaded = !state.failCopy;
      await route.fulfill({
        json: { outcome: state.failCopy ? 'failed' : 'imported', revision: state.failCopy ? 'revision-1' : 'revision-2' },
      });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/leases/acquire` && method === 'POST') {
      state.acquireCalls += 1;
      if (state.holdAcquire) await state.holdAcquire;
      await route.fulfill({ json: { status: 'editing', fence: 7 } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/leases/renew` && method === 'POST') {
      await route.fulfill({ json: { status: 'editing', fence: 7 } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/leases/release` && method === 'POST') {
      state.leaseReleases += 1;
      await route.fulfill({ json: { released: true } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/file` && method === 'POST') {
      await route.fulfill({ json: { content: state.fileContent, revision: 'revision-2' } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/write` && method === 'POST') {
      const body = request.postDataJSON();
      state.fileContent = body.content;
      state.writeCalls += 1;
      if (state.holdWrite) await state.holdWrite;
      await route.fulfill({ json: { revision: 'revision-3', fence: 7 } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/issues`) {
      if (method === 'POST') {
        state.issueCreates += 1;
        state.failIssueRefresh = true;
        await route.fulfill({ json: { issue_id: 'created-issue' } });
        return;
      }
      state.issueReads += 1;
      if (state.failIssueRefresh) {
        await route.fulfill({ status: 503, json: { detail: 'private-issue-response' } });
        return;
      }
      await route.fulfill({ json: { issues: [] } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/document-profiles` && method === 'GET') {
      await route.fulfill({
        json: {
          profiles: [{
            profile_id: 'generic_document', label: 'Универсальный документ',
            paper: 'A4', orientation: 'portrait', locale: 'ru-RU',
          }],
        },
      });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/documents/status` && method === 'POST') {
      await route.fulfill({
        json: {
          path: 'documents/paper', mode: 'draft', locale: 'ru-RU',
          latest_build: state.documentBuild,
          revision: state.vendorApplied ? 'revision-3' : 'revision-1',
          profile: {
            profile_id: 'generic_document', label: 'Универсальный документ',
            paper: 'A4', orientation: 'portrait', locale: 'ru-RU',
          },
          vendor_overlays: state.vendorApplied ? [{
            package_id: 'journal-kit', version: '1.0', license: 'LPPL-1.3c',
            file_count: 3, trusted: false, export_allowed: false,
          }] : [],
        },
      });
      return;
    }
    if (
      path === `/api/chats/${THREAD_ID}/workspace/documents/vendor/vendor-opaque-1`
      && method === 'POST'
    ) {
      const body = request.postDataJSON();
      expect(body).toEqual({
        path: 'documents/paper', expected_revision: 'revision-1', fence: 7,
      });
      state.vendorApplied = true;
      await route.fulfill({
        json: {
          outcome: 'imported', revision: 'revision-3',
          overlay: {
            package_id: 'journal-kit', version: '1.0', license: 'LPPL-1.3c',
            file_count: 3, trusted: false,
          },
        },
      });
      return;
    }
    if (path === '/api/chats/work-library') {
      await route.fulfill({ json: snapshot(state).library });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}`) {
      await route.fulfill({ json: { messages: [] } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/trace`) {
      await route.fulfill({ json: { traces: {} } });
      return;
    }
    if (path === '/api/chats/') {
      await route.fulfill({ json: { chats: [{ thread_id: THREAD_ID, title: 'Work Hub contract' }] } });
      return;
    }
    if (path === '/api/chats/models/catalog') {
      await route.fulfill({ json: { providers: [], models: [] } });
      return;
    }
    if (path === '/api/chats/models') {
      await route.fulfill({ json: { models: [] } });
      return;
    }
    if (path === '/api/chats/personas') {
      await route.fulfill({ json: [] });
      return;
    }
    if (path === '/api/chats/transcription/config') {
      await route.fulfill({ json: { enabled: false } });
      return;
    }
    if (path === '/api/billing/balance') {
      await route.fulfill({ json: { balance: 1000 } });
      return;
    }
    await route.fulfill({ json: {} });
  });
  return state;
}

async function expectNoHorizontalOverflow(page) {
  // Observe settled breakpoint/overlay transitions, keeping the strict zero
  // overflow threshold and the existing assertion timeout.
  await expect.poll(() => page.evaluate(() => (
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  ))).toBeLessThanOrEqual(0);
}

async function showPdfChecks(page) {
  const preview = page.getByRole('button', { name: 'Превью', exact: true });
  if (page.viewportSize().width < 1100) await preview.click();
  const checks = page.getByTestId('pdf-checks-bar');
  const toggle = checks.getByRole('button', { name: 'Проверки', exact: true });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  return checks;
}

async function editPdfSource(page, text) {
  await page.getByRole('button', { name: 'Материалы', exact: true }).click();
  await page.getByTestId('pdf-materials-panel').locator('[data-workspace-path="documents/paper/main.tex"]').click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const editor = page.getByRole('textbox', { name: 'Содержимое documents/paper/main.tex', exact: true });
  await editor.fill(text);
  return editor;
}

test.describe('Work Hub composition contract', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(
      !['chromium', 'tablet', 'mobile-chrome'].includes(testInfo.project.name),
      'The mandatory Work Hub gate covers desktop, tablet and mobile Chromium.',
    );
  });

  test('lazy Work loading is visible and Chat navigation remains available', async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const state = await installWorkApi(page);
    let releaseChunk;
    let heldChunks = 0;
    const held = new Promise((resolve) => { releaseChunk = resolve; });
    await page.route('**/static/js/**', async (route) => {
      const response = await route.fetch();
      const body = await response.body();
      // Locate the actual lazy Work module by its stable test boundary, not an
      // opaque production chunk filename or a simulated Workspace API delay.
      if (/['"]work-hub['"]/.test(body.toString('utf8'))) {
        heldChunks += 1;
        await held;
      }
      await route.fulfill({ response, body });
    });
    try {
      await page.goto(`/chat/${THREAD_ID}`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: 'Работа', exact: true }).click();
      await expect.poll(() => heldChunks).toBe(1);
      const loading = page.getByRole('status').filter({ hasText: 'Загружаю рабочее место…' });
      await expect(loading).toBeVisible();
      await expect(loading).not.toContainText('%');
      await expect(loading.locator('.chakra-spinner')).toHaveCSS('animation-name', 'none');
      await expectNoHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('work-lazy-loading.png') });
      await page.getByRole('button', { name: 'Чат', exact: true }).click();
      await expect(loading).toBeHidden();
      await expect(page).toHaveURL(new RegExp(`/chat/${THREAD_ID}$`));
      releaseChunk();
      await page.getByRole('button', { name: 'Работа', exact: true }).click();
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
      expect(state.activationCalls).toBe(0);
      expect(state.uploadCalls).toBe(0);
    } finally {
      releaseChunk();
    }
  });

  test('cold Library loading stays visible and can close without a surface change or a write', async ({ page }, testInfo) => {
    const state = await installWorkApi(page);
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    let heldChunks = 0;
    await page.route('**/static/js/**', async (route) => {
      const response = await route.fetch(); const body = await response.body();
      if (/['"]work-hub['"]/.test(body.toString('utf8'))) { heldChunks += 1; await held; }
      await route.fulfill({ response, body });
    });
    try {
      await page.goto(`/chat/${THREAD_ID}`, { waitUntil: 'domcontentloaded' });
      await triggerWorkbenchLibrary(page);
      const pending = page.getByTestId('workbench-library-pending');
      await expect(pending.getByText('Загружаю библиотеку…', { exact: true })).toBeVisible();
      await expect(pending.getByRole('status')).not.toContainText('%');
      await expect.poll(() => heldChunks).toBe(1);
      await expect(page).toHaveURL(new RegExp(`/chat/${THREAD_ID}$`));
      await pending.getByRole('button', { name: 'Закрыть библиотеку' }).click();
      await expect(pending).toHaveCount(0);
      release();
      await openWorkbenchLibrary(page);
      await expect(page.getByTestId('workbench-library')).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath('cold-library-recovered.png') });
      expect(state.activationCalls).toBe(0); expect(state.uploadCalls).toBe(0); expect(state.copyCalls).toBe(0);
    } finally { release(); }
  });

  test('issue draft survives responsive context replacement', async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workspace-file').click();
    const title = page.getByRole('textbox', { name: 'Новая задача для файла', exact: true });
    await title.fill('Черновик задачи');
    await page.getByRole('textbox', { name: 'Контекст', exact: true }).fill('Несохранённый контекст');
    await page.getByRole('spinbutton', { name: 'Строка от', exact: true }).fill('8');
    await page.getByRole('spinbutton', { name: 'Строка до', exact: true }).fill('4');
    await page.getByRole('button', { name: 'Добавить задачу', exact: true }).click();
    await expect(page.locator('form:visible').getByText('Конечная строка не может быть меньше начальной.')).toBeVisible();
    expect(state.issueCreates).toBe(0);
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.getByRole('button', { name: 'Контекст', exact: true }).click();
    await expect(title).toHaveValue('Черновик задачи');
    await expect(page.getByRole('spinbutton', { name: 'Строка до', exact: true })).toHaveValue('4');
    await expect(page.locator('form:visible').getByText('Конечная строка не может быть меньше начальной.')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.setViewportSize({ width: 393, height: 851 });
    await page.getByRole('tab', { name: 'Контекст', exact: true }).click();
    await expect(title).toHaveValue('Черновик задачи');
    await expect(page.getByRole('textbox', { name: 'Контекст', exact: true }))
      .toHaveValue('Несохранённый контекст');
    await page.getByRole('spinbutton', { name: 'Строка до', exact: true }).fill('9');
    await page.getByRole('button', { name: 'Добавить задачу', exact: true }).click();
    await expect.poll(() => state.issueCreates).toBe(1);
    await expect(title).toHaveValue('');
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(title).toHaveValue('');
    expect(state.issueCreates).toBe(1);
    await expectNoHorizontalOverflow(page);
    await page.addScriptTag({ content: axeCore.source });
    const serious = await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)));
    expect(serious).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath('issue-draft-continuity.png') });
  });

  test('confirmed empty issues remain stale after acknowledged create and failed refresh', async ({ page }, testInfo) => {
    await page.setViewportSize(testInfo.project.name === 'mobile-chrome'
      ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workspace-file').click();
    await expect.poll(() => state.issueReads).toBe(1);
    if (testInfo.project.name === 'mobile-chrome') {
      await page.getByRole('tab', { name: 'Контекст', exact: true }).click();
    }
    const title = page.getByRole('textbox', { name: 'Новая задача для файла', exact: true });
    await title.fill('Проверить источник');
    await page.getByRole('button', { name: 'Добавить задачу', exact: true }).click();
    await expect(page.getByRole('status').filter({
      hasText: 'Показаны последние доступные задачи. Обновление временно не удалось.',
    }))
      .toBeVisible();
    await expect(title).toHaveValue('');
    expect(state.issueCreates).toBe(1);
    await expect(page.getByText('Задачи временно недоступны.', { exact: false })).toHaveCount(0);
    await expect(page.getByText('private-issue-response')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await page.addScriptTag({ content: axeCore.source });
    const serious = await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)));
    expect(serious).toEqual([]);
  });

  test('passive URL navigation does not create a sandbox; explicit activation does', async ({ page }) => {
    const state = await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });

    await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
    await expect(page.getByTestId('work-workspace-state')).toContainText('не создано');
    expect(state.activationCalls).toBe(0);

    await page.getByTestId('work-activate').click();
    await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'ready');
    await expect(page.getByTestId('work-workspace-state')).toContainText('временная среда');
    expect(state.activationCalls).toBe(1);
    await expectNoHorizontalOverflow(page);
  });

  test('accepted activation supersedes an older passive refresh', async ({ page }) => {
    const state = await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
    let release;
    let acceptActivation;
    state.holdSnapshot = new Promise((resolve) => { release = resolve; });
    state.holdActivation = new Promise((resolve) => { acceptActivation = resolve; });
    try {
      await page.getByTestId('work-activate').click();
      await expect.poll(() => state.activationCalls).toBe(1);
      await page.getByRole('button', { name: 'Обновить рабочее состояние', exact: true }).click();
      await expect.poll(() => state.heldSnapshotCalls).toBe(1);
      acceptActivation();
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'ready');
      state.holdSnapshot = null;
      release();
      await expect.poll(() => state.heldSnapshotFinished).toBe(1);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'ready');
      expect(state.activationCalls).toBe(1);
      await expectNoHorizontalOverflow(page);
    } finally {
      acceptActivation();
      release();
    }
  });

  test('Library downloads without creating a sandbox or invoking copy', async ({ page }) => {
    const state = await installWorkApi(page);
    state.librarySaved = true;
    const body = 'owned synthetic Library content';
    // Native download handling differs by engine; do not rely on mock bodies.
    // Use a real, ephemeral HTTP artifact response behind the owned-route boundary.
    const server = createServer((request, response) => {
      response.writeHead(200, {
        'Content-Type': 'text/plain',
        'Content-Disposition': 'attachment; filename="brief.txt"',
        Connection: 'close',
      });
      response.end(body);
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const artifactUrl = `http://127.0.0.1:${server.address().port}/fixture`;
    // ActionLink opens a new tab; its initial navigation belongs to the
    // browser context, not the source page's route handlers.
    await page.context().route('**/api/service/files/v1/file-opaque-1/download',
      (route) => route.continue({ url: artifactUrl }));
    const downloads = [];
    const captureDownload = (download) => downloads.push(download);
    const watchPopup = (popup) => popup.on('download', captureDownload);
    page.on('download', captureDownload);
    page.context().on('page', watchPopup);
    try {
      await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
      await openWorkbenchLibrary(page);
      const link = page.getByRole('link', { name: 'Скачать brief.txt', exact: true });
      await expect(link).toBeVisible();
      await link.focus();
      await expect(link).toBeFocused();
      await link.press('Enter');
      // Engines may associate a _blank download with its popup, not the opener.
      await expect.poll(() => downloads.length).toBe(1);
      const [download] = downloads;
      try {
        expect(await download.failure()).toBeNull();
        expect(download.suggestedFilename()).toBe('brief.txt');
        const chunks = [];
        for await (const chunk of await download.createReadStream()) chunks.push(chunk);
        expect(Buffer.concat(chunks).toString()).toBe(body);
      } finally {
        await download.delete();
      }
      expect(state.activationCalls).toBe(0);
      expect(state.copyCalls).toBe(0);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
      await expectNoHorizontalOverflow(page);
    } finally {
      page.off('download', captureDownload);
      page.context().off('page', watchPopup);
      await new Promise((resolve) => server.close(resolve));
    }
  });

  test('Library cursor advances once per keyboard action without hiding retained files', async ({ page }) => {
    const state = await installWorkApi(page);
    state.librarySaved = true;
    const requested = [];
    await page.route(`**/api/chats/${THREAD_ID}/work`, async (route) => {
      const initial = snapshot(state);
      initial.library.next_cursor = 'cursor-2';
      await route.fulfill({ json: initial });
    });
    await page.route('**/api/chats/work-library*', async (route) => {
      const cursor = new URL(route.request().url()).searchParams.get('cursor');
      requested.push(cursor);
      expect(['cursor-2', 'cursor-3']).toContain(cursor);
      await route.fulfill({ json: {
        state: 'ready',
        items: [{
          file_id: cursor === 'cursor-2' ? 'second-file' : 'third-file',
          name: cursor === 'cursor-2' ? 'second.txt' : 'third.txt',
          availability: 'ready',
        }],
        next_cursor: cursor === 'cursor-2' ? 'cursor-3' : null,
        next_offset: null,
      } });
    });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await openWorkbenchLibrary(page);
    const more = page.getByRole('button', { name: 'Показать ещё', exact: true });
    await more.focus();
    await more.press('Enter');
    await expect(page.getByRole('link', { name: 'Скачать second.txt', exact: true })).toBeVisible();
    await more.focus();
    await more.press('Enter');
    await expect(page.getByRole('link', { name: 'Скачать third.txt', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Скачать brief.txt', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Скачать second.txt', exact: true })).toBeVisible();
    await expect(more).toHaveCount(0);
    expect(requested).toEqual(['cursor-2', 'cursor-3']);
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
  });

  test('Library page failure keeps files visible and supports keyboard retry', async ({ page }) => {
    const state = await installWorkApi(page);
    state.librarySaved = true;
    let attempts = 0;
    await page.route(`**/api/chats/${THREAD_ID}/work`, async (route) => {
      const initial = snapshot(state);
      initial.library.next_cursor = 'page-2';
      await route.fulfill({ json: initial });
    });
    await page.route('**/api/chats/work-library*', async (route) => {
      const cursor = new URL(route.request().url()).searchParams.get('cursor');
      if (!cursor) {
        await route.fulfill({ json: { ...snapshot(state).library, next_cursor: 'page-2' } });
        return;
      }
      attempts += 1;
      // The shared HTTP client performs two bounded GET retries.
      if (attempts <= 3) {
        await route.fulfill({ status: 503, json: { detail: 'private-error-marker' } });
      } else {
        await route.fulfill({ json: {
          state: 'ready', items: [{ file_id: 'second-file', name: 'second.txt', availability: 'ready' }],
          next_cursor: null, next_offset: null,
        } });
      }
    });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await openWorkbenchLibrary(page);
    await page.getByRole('button', { name: 'Показать ещё', exact: true }).click();
    await expect(page.locator('[role="status"]:visible').filter({
      hasText: 'Не удалось загрузить следующие файлы. Уже загруженные файлы доступны.',
    })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Скачать brief.txt', exact: true })).toBeVisible();
    await expect(page.getByText('private-error-marker')).toHaveCount(0);
    const retry = page.getByRole('button', { name: 'Повторить загрузку файлов', exact: true });
    await retry.focus();
    await retry.press('Enter');
    await expect(page.getByRole('link', { name: 'Скачать second.txt', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Скачать brief.txt', exact: true })).toBeVisible();
    await expect(retry).toHaveCount(0);
    expect(attempts).toBe(4);
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
  });

  test('direct intake creates the workspace and makes the file visible', async ({ page }) => {
    const state = await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');

    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'brief.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('synthetic work contract'),
    });

    await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'ready');
    await expect(page.getByTestId('workspace-file')).toHaveAttribute('data-workspace-path', 'brief.txt');
    expect(state.uploaded).toBe(true);
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
  });

  test('cancelled upload reconciles Library and retries the same intent', async ({ page }) => {
    const state = await installWorkApi(page);
    const intents = [];
    let release;
    let aborted;
    const held = new Promise((resolve) => { release = resolve; });
    const finished = new Promise((resolve) => { aborted = resolve; });
    await page.route(`**/api/chats/${THREAD_ID}/work/upload`, async (route) => {
      const match = route.request().postData().match(/name="upload_intent_id"\r\n\r\n([^\r\n]+)/);
      intents.push(match?.[1]);
      state.librarySaved = true;
      if (intents.length === 1) {
        await held;
        try { await route.abort('aborted'); } finally { aborted(); }
        return;
      }
      await route.fulfill({ json: {
        outcome: 'library_saved', revision: '',
        file: { file_id: 'file-opaque-1', name: 'brief.txt', availability: 'ready' },
      } });
    });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('cancel recovery fixture'),
    });
    await expect.poll(() => intents.length).toBe(1);
    const cancel = page.getByRole('button', { name: 'Отменить', exact: true });
    await cancel.focus();
    await cancel.press('Enter');
    await expect(page.getByText('Загрузка отменена. Проверьте библиотеку перед повтором.', { exact: true })).toBeVisible();
    release();
    await finished;
    await expect(page.getByText('Файл добавлен в библиотеку и рабочее место', { exact: true })).toHaveCount(0);
    const retry = page.getByRole('button', { name: 'Проверить и повторить', exact: true });
    await retry.focus();
    await retry.press('Enter');
    await openWorkbenchLibrary(page);
    await expect(page.locator('[data-testid="work-library-file"]:visible')
      .getByTestId('work-library-outcome')).toHaveText('Источник сохранён только в библиотеке');
    await expect(page.getByRole('link', { name: 'Скачать brief.txt', exact: true })).toBeVisible();
    expect(intents).toHaveLength(2);
    expect(intents[0]).toMatch(/^[\da-f-]{36}$/);
    expect(intents[1]).toBe(intents[0]);
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
  });

  test('Library-only outcome wraps without covering download or copy', async ({ page }) => {
    const state = await installWorkApi(page);
    state.deferUpload = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await openWorkbenchLibrary(page);
    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('Library layout fixture'),
    });
    const item = page.locator('[data-testid="work-library-file"]:visible');
    const outcome = item.getByTestId('work-library-outcome');
    await expect(outcome).toHaveText('Источник сохранён только в библиотеке');
    await expect(outcome).toBeVisible();
    const geometry = await outcome.evaluate((element) => {
      const badge = element.getBoundingClientRect();
      const card = element.closest('[data-testid="work-library-file"]').getBoundingClientRect();
      return { fits: badge.left >= card.left && badge.right <= card.right,
        wraps: getComputedStyle(element).whiteSpace === 'normal',
        clipped: element.scrollWidth > element.clientWidth };
    });
    expect(geometry).toEqual({ fits: true, wraps: true, clipped: false });
    const download = item.getByRole('link', { name: 'Скачать brief.txt', exact: true });
    await download.focus();
    await expect(download).toBeFocused();
    await expect(item.getByRole('button', { name: 'Создать и добавить', exact: true })).toBeEnabled();
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: `tmp_e2e/library-outcome-${test.info().project.name}.png` });
  });

  test('Library delivery toast clears download and copy in a short viewport', async ({ page }) => {
    await page.setViewportSize({ width: page.viewportSize().width, height: 550 });
    const state = await installWorkApi(page);
    state.deferUpload = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await openWorkbenchLibrary(page);
    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('toast clearance fixture'),
    });
    const item = page.locator('[data-testid="work-library-file"]:visible');
    const download = item.getByRole('link', { name: 'Скачать brief.txt', exact: true });
    const copy = item.getByRole('button', { name: 'Создать и добавить', exact: true });
    await download.scrollIntoViewIfNeeded();
    const toast = page.locator('.chakra-toast__inner').last();
    await expect(toast).toBeVisible();
    await expect.poll(async () => {
      const [notice, actions] = await Promise.all([
        toast.boundingBox(), item.locator('[data-toast-protected-actions]').boundingBox(),
      ]);
      return notice && actions ? actions.y - notice.y - notice.height : -1;
    }).toBeGreaterThanOrEqual(8);
    await download.click({ trial: true });
    await download.focus();
    await expect(download).toBeFocused();
    await copy.click({ trial: true });
    await copy.focus();
    await expect(copy).toBeFocused();
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: `tmp_e2e/library-toast-${test.info().project.name}.png` });
  });

  test('upload retry selection survives source-panel replacement', async ({ page }) => {
    const state = await installWorkApi(page);
    const intents = [];
    await page.route(`**/api/chats/${THREAD_ID}/work/upload`, async (route) => {
      const match = route.request().postData().match(/name="upload_intent_id"\r\n\r\n([^\r\n]+)/);
      intents.push(match?.[1]);
      await route.fulfill({ status: 503, json: { detail: 'unavailable' } });
    });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'retry-source.txt', mimeType: 'text/plain', buffer: Buffer.from('panel recovery fixture'),
    });
    const retry = page.getByRole('button', { name: 'Проверить и повторить', exact: true });
    await expect(retry).toBeVisible();
    await openWorkbenchLibrary(page);
    await expect(retry).toBeVisible();
    await retry.focus();
    await retry.press('Enter');
    await expect.poll(() => intents.length).toBe(2);
    await expect(retry).toBeVisible();
    expect(intents[0]).toMatch(/^[\da-f-]{36}$/);
    expect(intents[1]).toBe(intents[0]);
    expect(state.activationCalls).toBe(0);
    await expect(page.getByText('Статус не подтверждён. Проверьте библиотеку перед повтором. Повтор относится к той же загрузке.', { exact: true })).toBeVisible();
    await expect(page.getByText(/upload[_ ]intent/i)).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: `tmp_e2e/upload-selection-${test.info().project.name}.png` });
  });

  test('changed-file upload explains reselect recovery without internal terminology', async ({ page }) => {
    const state = await installWorkApi(page);
    await page.route(`**/api/chats/${THREAD_ID}/work/upload`, (route) => route.fulfill({
      status: 409, json: { detail: 'upload_intent_conflict' },
    }));
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'changed-source.txt', mimeType: 'text/plain', buffer: Buffer.from('changed fixture'),
    });
    await expect(page.getByText('Содержимое файла отличается от предыдущей попытки. Выберите файл заново.', { exact: true })).toBeVisible();
    await expect(page.getByText('changed-source.txt', { exact: true })).toBeVisible();
    await expect(page.getByText(/upload[_ ]intent/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Проверить и повторить', exact: true })).toHaveCount(0);
    await openWorkbenchLibrary(page);
    await expect(page.getByRole('button', { name: /^(Добавить файл|Добавить файл в библиотеку и рабочее место)$/ })).toBeEnabled();
    expect(state.activationCalls).toBe(0);
    await expectNoHorizontalOverflow(page);
  });

  test('save feedback clears editor actions and tracks a short viewport', async ({ page }) => {
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workspace-file').click();
    await page.getByLabel('Содержимое brief.txt').fill('saved shelf fixture');
    await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
    await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
    const toast = page.locator('.chakra-toast__inner').last();
    await expect(toast).toBeVisible();
    const clearance = async () => {
      const [notice, actions] = await Promise.all([
        toast.boundingBox(), page.getByTestId('workspace-editor-actions').boundingBox(),
      ]);
      return notice && actions ? actions.y - notice.y - notice.height : -1;
    };
    await expect.poll(clearance).toBeGreaterThanOrEqual(8);
    await page.setViewportSize({ width: 393, height: 550 });
    await expect.poll(clearance).toBeGreaterThanOrEqual(8);
    await expectNoHorizontalOverflow(page);
    expect(state.fileContent).toBe('saved shelf fixture');
  });

  test('typing during save stays dirty and navigation still requires confirmation', async ({ page }) => {
    // Two writes, a held acknowledgement, axe and dialog focus restoration.
    // Keep the individual assertions strict, with a bounded whole-flow budget.
    test.setTimeout(60_000);
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    let releaseWrite;
    let releaseRefresh;
    state.holdWrite = new Promise((resolve) => { releaseWrite = resolve; });
    try {
      await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
      await page.getByTestId('workspace-file').click();
      const editor = page.getByLabel('Содержимое brief.txt');
      await editor.fill('submitted draft');
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect.poll(() => state.writeCalls).toBe(1);
      await editor.fill('newer unsent draft');
      state.holdSnapshot = new Promise((resolve) => { releaseRefresh = resolve; });
      state.holdWrite = null;
      releaseWrite();
      await expect.poll(() => state.heldSnapshotCalls).toBe(1);
      await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeEnabled();
      await expect(editor).toHaveValue('newer unsent draft');
      expect(state.fileContent).toBe('submitted draft');
      await page.getByRole('button', { name: 'Чат', exact: true }).click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Продолжить редактирование' })).toBeFocused();
      await page.addScriptTag({ content: axeCore.source });
      const accessibilityFailures = await page.evaluate(async () => {
        const result = await window.axe.run(document.querySelector('[role="alertdialog"]'));
        return result.violations.filter((item) => ['serious', 'critical'].includes(item.impact))
          .map((item) => item.id);
      });
      expect(accessibilityFailures).toEqual([]);
      await dialog.getByRole('button', { name: 'Продолжить редактирование' }).click();
      await expect(editor).toBeFocused();
      await expect(editor).toHaveValue('newer unsent draft');
      await editor.press('Control+s');
      await expect.poll(() => state.writeCalls).toBe(2);
      await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
      expect(state.fileContent).toBe('newer unsent draft');
      await expect.poll(() => state.heldSnapshotCalls).toBe(2);
      state.holdSnapshot = null;
      releaseRefresh();
      await expect.poll(() => state.heldSnapshotFinished).toBe(2);
      await expect(editor).toHaveValue('newer unsent draft');
      await expectNoHorizontalOverflow(page);
    } finally {
      releaseRefresh?.();
      releaseWrite();
    }
  });

  test('ready editor fills its available Work surface height', async ({ page }) => {
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workspace-file').click();
    const actions = page.getByTestId('workspace-editor-actions');
    await expect(actions).toBeVisible();
    const geometry = await actions.evaluate((element) => {
      const chain = [];
      for (let node = element; node; node = node.parentElement) {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        chain.push({ tag: node.tagName, role: node.getAttribute('role'),
          top: rect.top, height: rect.height, display: style.display,
          flex: style.flex, direction: style.flexDirection });
      }
      return chain;
    });
    await expect.poll(async () => {
      const box = await actions.boundingBox();
      return box ? Math.abs(page.viewportSize().height - box.y - box.height) : Infinity;
    }, { message: JSON.stringify(geometry) }).toBeLessThanOrEqual(2);
    await expectNoHorizontalOverflow(page);
  });

  test('discard restores the current baseline without write or lease release', async ({ page }) => {
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workspace-file').click();
    const editor = page.getByLabel('Содержимое brief.txt');
    await editor.fill('local discard fixture');
    const discard = page.getByRole('button', { name: 'Отменить', exact: true });
    await discard.focus();
    await discard.press('Enter');
    await expect(editor).toHaveValue(state.fileContent);
    await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled();
    expect(state.writeCalls).toBe(0);
    expect(state.leaseReleases).toBe(0);
    await expectNoHorizontalOverflow(page);
  });

  test('conflict copy uses the latest local draft and keeps it editable', async ({ page }) => {
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    // Controlled browser boundary: never read or overwrite the host OS clipboard.
    await page.addInitScript(() => {
      window.workCopyCalls = [];
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async (text) => { window.workCopyCalls.push(text); },
      } });
    });
    let rejectedWrites = 0;
    await page.route(`**/api/chats/${THREAD_ID}/workspace/write`, (route) => {
      rejectedWrites += 1;
      return route.fulfill({ status: 409, json: { detail: 'private-conflict-marker' } });
    });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('workspace-file').click();
    const editor = page.getByLabel('Содержимое brief.txt');
    await editor.fill('draft at rejected save');
    await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
    const copy = page.getByRole('button', { name: 'Скопировать мои изменения', exact: true });
    await expect(copy).toBeVisible();
    await editor.fill('newer local draft');
    await copy.focus();
    await copy.press('Enter');
    await expect.poll(() => page.evaluate(() => window.workCopyCalls)).toEqual(['newer local draft']);
    const toast = page.locator('.chakra-toast__inner').last();
    await expect(toast).toBeVisible();
    await expect.poll(async () => {
      const [notice, action] = await Promise.all([toast.boundingBox(), copy.boundingBox()]);
      return notice && action ? action.y - notice.y - notice.height : -1;
    }).toBeGreaterThanOrEqual(8);
    await expect(editor).toHaveValue('newer local draft');
    await expect(editor).toBeEditable();
    await expect(page.getByText('private-conflict-marker')).toHaveCount(0);
    expect(state.fileContent).toBe('synthetic work contract');
    expect(rejectedWrites).toBe(1);
    await expectNoHorizontalOverflow(page);
  });

  test('a lease acquired after leaving Work is released and explicit reacquisition preserves the editor', async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const state = await installWorkApi(page);
    state.active = true;
    state.uploaded = true;
    let finishAcquire;
    state.holdAcquire = new Promise((resolve) => { finishAcquire = resolve; });
    try {
      await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
      await page.getByTestId('workspace-file').click();
      await expect.poll(() => state.acquireCalls).toBe(1);
      await page.getByRole('button', { name: 'Чат', exact: true }).click();
      await expect(page).not.toHaveURL(/surface=work/);
      state.holdAcquire = null;
      finishAcquire();
      await expect.poll(() => state.leaseReleases).toBe(1);
      await page.getByRole('button', { name: 'Работа', exact: true }).click();
      const editor = page.getByLabel('Содержимое brief.txt');
      await expect(editor).toHaveValue('synthetic work contract');
      await expect(editor).toHaveAttribute('readonly', '');
      await page.getByRole('button', { name: 'Получить право', exact: true }).click();
      await expect.poll(() => state.acquireCalls).toBe(2);
      await expect(editor).not.toHaveAttribute('readonly', '');
      await editor.fill('draft after explicit reacquisition');
      await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeEnabled();
      await expectNoHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('lease-recovery.png') });
    } finally {
      finishAcquire();
    }
  });

  for (const failCopy of [false, true]) {
    test(`deferred upload uses explicit recovery copy: ${failCopy ? 'failure' : 'success'}`, async ({ page }) => {
      const state = await installWorkApi(page);
      state.deferUpload = true;
      state.failCopy = failCopy;
      await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
      await page.getByTestId('work-upload-input').setInputFiles({
        name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('deferred source'),
      });
      await openWorkbenchLibrary(page);
      const item = page.locator('[data-testid="work-library-file"]:visible').filter({ hasText: 'brief.txt' });
      await expect(item).toBeVisible();
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
      expect(state.copyCalls).toBe(0);
      expect(state.uploadCalls).toBe(1);
      await item.getByRole('button', { name: 'Создать и добавить' }).click();
      await expect.poll(() => state.copyCalls).toBe(1);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'ready');
      if (failCopy) {
        await expect(page.getByText('Добавить файл не удалось', { exact: true })).toBeVisible();
        await expect(item).not.toContainText('сохранён без перезаписи');
        expect(state.uploaded).toBe(false);
      } else {
        await expect(page.getByText('Файл добавлен в рабочее место', { exact: true })).toBeVisible();
        await expect(item).toContainText('добавлен');
        expect(state.uploaded).toBe(true);
      }
      expect(state.activationCalls).toBe(1);
      expect(state.uploadCalls).toBe(1);
      await expectNoHorizontalOverflow(page);
    });
  }

  test('queued document shows one visible build status without duplicate project copy or premature audit success', async ({ page }, testInfo) => {
    await page.setViewportSize(testInfo.project.name === 'mobile-chrome'
      ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    const state = await installWorkApi(page);
    state.active = true;
    state.documentReady = true;
    state.documentBuild = { build_id: 'queued-build', state: 'queued', artifacts: [] };
    await page.goto(`/chat/${THREAD_ID}?surface=pdf`, { waitUntil: 'domcontentloaded' });
    await showPdfChecks(page);
    const pipeline = page.locator('[aria-label="Этапы подготовки документа"]:visible');
    await expect(pipeline).toHaveCount(1);
    await expect(pipeline).toContainText('ожидает запуска');
    await expect(pipeline).not.toContainText('проверен');
    await expect(pipeline).not.toContainText('пройден');
    await expect(page.getByText('Универсальный документ · Русский · Черновик', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('pdf-build-activity').getByRole('status')).toHaveText('Сборка PDF в очереди');
    await expect(page.getByTestId('pdf-studio-toolbar').locator('.chakra-spinner')).toHaveCount(0);
    await page.addScriptTag({ content: axeCore.source });
    const failures = await page.evaluate(async () => {
      const result = await window.axe.run(document.querySelector('[data-testid="pdf-studio"]'));
      return result.violations.filter((item) => ['serious', 'critical'].includes(item.impact))
        .map((item) => item.id);
    });
    expect(failures).toEqual([]);
    await expectNoHorizontalOverflow(page);
  });

  test('PDF preview read failure stays inline and keyboard retry opens the owned preview', async ({ page }, testInfo) => {
    await page.setViewportSize(testInfo.project.name === 'mobile-chrome'
      ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    const state = await installWorkApi(page);
    state.active = true;
    state.documentReady = true;
    state.documentBuild = {
      build_id: 'preview-build', state: 'preview_ready',
      artifacts: [{ role: 'pdf', artifact_id: 'preview-pdf' }],
    };
    let reads = 0;
    await page.route('**/documents/builds/preview-build/artifacts/preview-pdf', async (route) => {
      reads += 1;
      if (reads === 1) {
        await route.fulfill({ status: 503, json: { detail: 'private-preview-response' } });
      } else {
        await route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' });
      }
    });
    await page.goto(`/chat/${THREAD_ID}?surface=pdf`, { waitUntil: 'domcontentloaded' });
    const previewPane = page.getByRole('button', { name: 'Превью', exact: true });
    if (page.viewportSize().width < 1100) await previewPane.click();
    const preview = page.getByRole('button', { name: 'Открыть PDF', exact: true });
    await preview.focus();
    await preview.press('Enter');
    await expect(page.getByRole('alert').filter({ hasText: 'Не удалось открыть превью.' })).toBeVisible();
    await expect(page.getByText('private-preview-response', { exact: true })).toHaveCount(0);
    await preview.focus();
    await preview.press('Enter');
    const visiblePreview = page.locator('iframe[title="Предпросмотр PDF"]:visible');
    await expect(visiblePreview).toHaveCount(1);
    await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
    await expect(visiblePreview).toHaveAttribute('src', /^blob:/);
    const previewSource = await visiblePreview.getAttribute('src');
    await page.getByRole('button', { name: 'Чат', exact: true }).click();
    await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(0);
    await page.getByRole('button', { name: 'PDF', exact: true }).click();
    await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
    await expect(visiblePreview).toHaveAttribute('src', previewSource);
    if (testInfo.project.name === 'chromium') {
      await page.setViewportSize({ width: 1024, height: 900 });
      // Open PDF selected Preview; a breakpoint must retain that explicit choice.
      await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
      await previewPane.click();
      await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
      await expect(visiblePreview).toHaveAttribute('src', previewSource);
      await page.getByRole('button', { name: 'Редактор', exact: true }).click();
      await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(0);
      await page.setViewportSize({ width: 393, height: 851 });
      await previewPane.click();
      await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
      await expect(visiblePreview).toHaveAttribute('src', previewSource);
      await page.setViewportSize({ width: 1440, height: 900 });
      await expect(page.getByRole('button', { name: 'PDF', exact: true })).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
      await expect(visiblePreview).toHaveAttribute('src', previewSource);
    }
    await expect(page.getByRole('alert').filter({ hasText: 'Не удалось открыть превью.' })).toHaveCount(0);
    expect(reads).toBe(2);
    await page.addScriptTag({ content: axeCore.source });
    const failures = await page.evaluate(async () => {
      const result = await window.axe.run(document.querySelector('[data-testid="pdf-studio"]'));
      return result.violations.filter((item) => ['serious', 'critical'].includes(item.impact))
        .map((item) => item.id);
    });
    expect(failures).toEqual([]);
    await expectNoHorizontalOverflow(page);
  });

  test('PDF publication status recovery never resubmits and retains the editor draft', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === 'tablet', 'Dedicated desktop/mobile recovery matrix.');
    test.setTimeout(60_000);
    const mobile = testInfo.project.name === 'mobile-chrome';
    await page.setViewportSize(mobile ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const state = await installWorkApi(page);
    state.active = true;
    state.documentReady = true;
    // Faithful project snapshot: Workspace does not know the backend outbox.
    state.documentBuild = {
      build_id: 'publication-build', state: 'ready', final: true,
      artifacts: [{ artifact_id: 'final-pdf', role: 'pdf' }],
    };
    let publishCalls = 0;
    let statusCalls = 0;
    let failStatus = false;
    let publicationState = null;
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.route('**/documents/builds/publication-build/artifacts/final-pdf/publish', async (route) => {
      publishCalls += 1;
      publicationState = 'pending_delivery';
      failStatus = true;
      await route.fulfill({ status: 202, json: { publication_state: publicationState } });
    });
    await page.route('**/documents/builds/publication-build', async (route) => {
      statusCalls += 1;
      if (failStatus) {
        failStatus = false;
        await route.fulfill({ status: 503, json: { detail: 'private-publication-response' } });
        return;
      }
      if (publishCalls) publicationState = 'delivered';
      await route.fulfill({ json: { ...state.documentBuild, publication_state: publicationState } });
    });
    await page.goto(`/chat/${THREAD_ID}?surface=pdf`, { waitUntil: 'domcontentloaded' });
    const editor = await editPdfSource(page, 'Несохранённая правка документа');
    await showPdfChecks(page);
    const publish = page.getByRole('button', { name: 'Сохранить в Библиотеку', exact: true });
    await expect(publish).toBeEnabled();
    await publish.focus();
    await publish.press('Enter');
    const recovery = page.locator('[aria-label="Состояние сохранения документа"]:visible');
    await expect(recovery).toContainText('Оно могло завершиться');
    await expect(publish).toBeDisabled();
    expect(publishCalls).toBe(1);
    await expect(page.getByText('private-publication-response', { exact: true })).toHaveCount(0);
    const check = recovery.getByRole('button', { name: 'Проверить сохранение', exact: true });
    await check.focus();
    await expect(check).toBeFocused();
    const queuedToast = page.locator('.chakra-toast__inner')
      .filter({ hasText: 'Сохранение поставлено в очередь' });
    await expect(queuedToast).toBeVisible();
    await expect.poll(() => page.evaluate(() => {
      const toasts = [...document.querySelectorAll('.chakra-toast__inner')]
        .filter((element) => element.textContent.includes('Сохранение поставлено в очередь'));
      if (toasts.length !== 1) return false;
      return [...document.querySelectorAll('[data-toast-protected-actions]')].every((element) => {
        const shelf = element.getBoundingClientRect();
        if (!shelf.width || !shelf.height || shelf.top >= window.innerHeight || shelf.bottom <= 0) return true;
        return toasts.every((toast) => {
          const rect = toast.getBoundingClientRect();
          return rect.bottom <= shelf.top || rect.top >= shelf.bottom
            || rect.right <= shelf.left || rect.left >= shelf.right;
        });
      });
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('publication-recovery.png') });
    await check.press('Enter');
    const pipeline = page.locator('[aria-label="Этапы подготовки документа"]:visible');
    await expect(pipeline).toContainText('Сохранён в Библиотеке');
    await expect(recovery).toHaveCount(0);
    expect(publishCalls).toBe(1);
    if (mobile) await page.getByRole('button', { name: 'Редактор', exact: true }).click();
    await expect(editor).toHaveValue('Несохранённая правка документа');
    expect(state.writeCalls).toBe(0);
    if (mobile) await page.getByRole('button', { name: 'Превью', exact: true }).click();
    await page.addScriptTag({ content: axeCore.source });
    const violations = await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact))
      .map((item) => ({ id: item.id, nodes: item.nodes.map((node) => ({ html: node.html, failure: node.failureSummary })) })));
    expect(violations).toEqual([]);
    await expectNoHorizontalOverflow(page);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await showPdfChecks(page);
    await expect(pipeline).toContainText('Сохранён в Библиотеке');
    await expect(publish).toBeDisabled();
    expect(publishCalls).toBe(1);
    expect(statusCalls).toBeGreaterThanOrEqual(4);
    expect(pageErrors).toEqual([]);
  });

  test('PDF publication deadline releases observation without cancelling or repeating delivery', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === 'tablet', 'Dedicated desktop/mobile deadline matrix.');
    test.setTimeout(60_000);
    const mobile = testInfo.project.name === 'mobile-chrome';
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.setViewportSize(mobile ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    const state = await installWorkApi(page);
    state.active = true;
    state.documentReady = true;
    state.documentBuild = {
      build_id: 'deadline-build', state: 'ready', final: true,
      artifacts: [{ artifact_id: 'deadline-pdf', role: 'pdf' }],
    };
    let publishCalls = 0;
    let statusCalls = 0;
    let release;
    const heldRead = new Promise((resolve) => { release = resolve; });
    await page.route('**/documents/builds/deadline-build/artifacts/deadline-pdf/publish', async (route) => {
      publishCalls += 1;
      await route.fulfill({ status: 202, json: { publication_state: 'pending_delivery' } });
    });
    await page.route('**/documents/builds/deadline-build', async (route) => {
      statusCalls += 1;
      if (publishCalls && statusCalls === 2) {
        await heldRead;
        try {
          await route.fulfill({ json: { ...state.documentBuild, publication_state: 'delivered' } });
        } catch { /* The deadline aborts this request; the server job stays durable. */ }
        return;
      }
      await route.fulfill({ json: {
        ...state.documentBuild, publication_state: publishCalls ? 'delivered' : null,
      } });
    });
    try {
      await page.goto(`/chat/${THREAD_ID}?surface=pdf`, { waitUntil: 'domcontentloaded' });
      const editor = await editPdfSource(page, 'Правка во время долгого сохранения');
      await showPdfChecks(page);
      const publish = page.getByRole('button', { name: 'Сохранить в Библиотеку', exact: true });
      await expect(publish).toBeEnabled();
      await page.clock.install();
      await publish.click();
      await expect.poll(() => statusCalls).toBe(2);
      const recovery = page.locator('[aria-label="Состояние сохранения документа"]:visible');
      await expect(recovery).toContainText('Проверяю сохранение');
      await page.clock.fastForward(300_000);
      await expect(recovery).toContainText('Оно могло завершиться');
      await expect(publish).toBeDisabled();
      const check = recovery.getByRole('button', { name: 'Проверить сохранение', exact: true });
      await expect(check).toBeEnabled();
        await check.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath('publication-deadline.png') });
      await page.addScriptTag({ content: axeCore.source });
      const violations = await page.evaluate(async () => (await window.axe.run()).violations
        .filter((item) => ['serious', 'critical'].includes(item.impact))
        .map((item) => ({ id: item.id, nodes: item.nodes.map((node) => ({ html: node.html, failure: node.failureSummary })) })));
      expect(violations).toEqual([]);
      await check.focus();
      await check.press('Enter');
      await expect(page.locator('[aria-label="Этапы подготовки документа"]:visible'))
        .toContainText('Сохранён в Библиотеке');
      expect(publishCalls).toBe(1);
      expect(statusCalls).toBe(3);
      expect(state.writeCalls).toBe(0);
      if (mobile) await page.getByRole('button', { name: 'Редактор', exact: true }).click();
      await expect(editor).toHaveValue('Правка во время долгого сохранения');
      await expectNoHorizontalOverflow(page);
      expect(pageErrors).toEqual([]);
    } finally {
      release();
    }
  });

  test('installs a Library vendor kit through the guarded project action', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'Document vendor flow runs once on desktop.');
    const state = await installWorkApi(page);
    state.active = true;
    state.documentReady = true;
    state.vendorAvailable = true;
    await page.goto(`/chat/${THREAD_ID}?surface=pdf`, { waitUntil: 'domcontentloaded' });

    await page.getByRole('button', { name: 'Оформление', exact: true }).click();
    const documentPanel = page.getByRole('dialog');
    await expect(documentPanel.getByText('Шаблон издателя', { exact: true })).toBeVisible();
    await documentPanel.getByRole('button', { name: 'Добавить в проект' }).click();

    await expect.poll(() => state.vendorApplied).toBe(true);
    await expect(documentPanel.getByText('journal-kit', { exact: true })).toBeVisible();
    await expect(documentPanel.getByText(/1\.0 · изолирован/)).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test('dirty navigation is cancelled or confirmed without losing control of the lease', async ({ page }) => {
    const state = await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Работа', exact: true }).click();
    await page.getByTestId('work-upload-input').setInputFiles({
      name: 'brief.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('synthetic work contract'),
    });
    await page.getByTestId('workspace-file').click();
    const editor = page.getByLabel('Содержимое brief.txt');
    await editor.fill('local unsaved draft');

    await page.getByRole('button', { name: 'Чат', exact: true }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Продолжить редактирование' })).toBeFocused();
    await dialog.getByRole('button', { name: 'Продолжить редактирование' }).click();
    await expect(editor).toHaveValue('local unsaved draft');
    expect(state.leaseReleases).toBe(0);

    await page.evaluate(() => window.history.back());
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Продолжить редактирование' }).click();
    await expect(editor).toHaveValue('local unsaved draft');

    await page.getByRole('button', { name: 'Чат', exact: true }).click();
    await dialog.getByRole('button', { name: 'Отбросить и перейти' }).click();
    await expect(page).toHaveURL(new RegExp(`/chat/${THREAD_ID}$`));
    await expect.poll(() => state.leaseReleases).toBe(1);
  });

  test('uses tabs, context overlay or three panels for the active viewport', async ({ page }, testInfo) => {
    await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('work-activate').click();

    const mobileTabs = page.getByTestId('work-mobile-tabs');
    const contextAction = page.getByRole('button', { name: 'Контекст', exact: true });
    if (testInfo.project.name === 'mobile-chrome') {
      await expect(mobileTabs).toBeVisible();
      await page.getByRole('tab', { name: 'Контекст' }).click();
      await expect(page.getByRole('tab', { name: 'Агент' })).toBeVisible();
    } else if (testInfo.project.name === 'tablet') {
      await expect(mobileTabs).toHaveCount(0);
      await expect(contextAction).toBeVisible();
      await contextAction.click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(page.getByRole('dialog').getByText('Контекст', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Закрыть контекст' }).click();
      await expect(contextAction).toBeFocused();
    } else {
      await expect(mobileTabs).toHaveCount(0);
      await expect(contextAction).toBeHidden();
      await expect(page.getByRole('tab', { name: 'История' })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
  });

  test('keeps actions reachable in a short narrow viewport', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile-chrome', 'Short viewport is a mobile contract.');
    await page.setViewportSize({ width: 393, height: 500 });
    await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });

    await expect(page.getByTestId('work-activate')).toBeVisible();
    await expect(page.getByTestId('work-upload-input')).toBeAttached();
    await expectNoHorizontalOverflow(page);
  });

  test('reflows a 1440px workbench at 200% equivalent zoom', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'Zoom contract runs once on desktop Chromium.');
    // Browser zoom halves the CSS viewport. A 720x450 viewport is the stable,
    // engine-independent equivalent of 1440x900 at 200%.
    await page.setViewportSize({ width: 720, height: 450 });
    await installWorkApi(page);
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });

    await expect(page.getByTestId('work-mobile-tabs')).toBeVisible();
    await expect(page.getByTestId('work-activate')).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
