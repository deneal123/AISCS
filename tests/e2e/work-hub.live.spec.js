const { test, expect } = require('@playwright/test');
const { openWorkbenchLibrary, closeWorkbenchLibrary } = require('./helpers/workbenchLibrary');
const { revealWorkspaceFile } = require('./helpers/workspaceTree');
const { safeLiveRequest } = require('./helpers/safeLiveRequest');
const { collectLiveWorkTimings } = require('./helpers/liveWorkTimings');
const fs = require('fs/promises');
const path = require('path');
const { createHash } = require('crypto');

const timingCollectors = new WeakMap();

const liveEnabled = process.env.E2E_LIVE_WORK_HUB === '1';
const authToken = process.env.E2E_AUTH_TOKEN || '';
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';

test.use({ trace: 'off', video: 'off' });
test.setTimeout(90_000);

async function authenticate(context) {
  await context.addCookies([{ name: 'auth_token', value: authToken, url: baseURL }]);
  await context.addInitScript((token) => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', token);
  }, authToken);
}

async function createThread(page) {
  const response = await safeLiveRequest('create_thread', () => page.request.post('/api/chats/', {
    data: { title: `S28 Work Hub ${Date.now()}` },
  }));
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  expect(typeof payload.thread_id).toBe('string');
  return payload.thread_id;
}

async function removeThread(page, threadId) {
  const response = await safeLiveRequest('delete_thread', () => page.request.delete(`/api/chats/${threadId}`));
  expect(response.ok()).toBeTruthy();
}

async function openWork(page, threadId) {
  await page.goto(`/chat/${threadId}?surface=work`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('work-hub')).toBeVisible({ timeout: 20_000 });
}

async function upload(page, name, content, onSaved = () => {}, mimeType = 'text/plain') {
  // A first upload can include explicit sandbox activation and image startup.
  // Keep this live-only wait above the normal UI timeout so a healthy cold
  // start is not mistaken for a missing request.
  // Capture the initiating request, then await *its* response. This binds the
  // result assertion to the exact multipart mutation while background snapshot
  // refreshes continue independently.
  const isUploadRequest = (request) => (
    request.method() === 'POST'
    && new URL(request.url()).pathname.endsWith('/work/upload')
  );
  const requestPromise = page.waitForRequest(isUploadRequest, { timeout: 60_000 });
  const responsePromise = page.waitForResponse(
    (response) => isUploadRequest(response.request()),
    { timeout: 60_000 },
  );
  const failurePromise = page.waitForEvent('requestfailed', {
    predicate: isUploadRequest,
    timeout: 60_000,
  }).then(() => {
    throw new Error('live_work_upload_transport_unavailable');
  });
  await page.getByTestId('work-upload-input').setInputFiles({
    name,
    mimeType,
    buffer: Buffer.from(content),
  });
  const request = await requestPromise;
  expect(new URL(request.url()).pathname).toMatch(/\/work\/upload$/);
  const response = await Promise.race([responsePromise, failurePromise]);
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  // Register the durable source before asserting the workspace outcome:
  // library_saved is not positive acceptance, but its owned fixture still
  // needs finally-cleanup when that assertion fails.
  onSaved(result.file.file_id);
  expect(['imported', 'kept']).toContain(result.outcome);
  await expect(page.getByTestId('work-hub')).toHaveAttribute(
    'data-workspace-state',
    'ready',
    { timeout: 20_000 },
  );
  await expect(
    page.locator(`[data-testid="workspace-file"][data-workspace-path="${name}"]`),
  ).toBeVisible({ timeout: 20_000 });
  return result;
}

async function noHorizontalOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    offenders: Array.from(document.querySelectorAll('body *'))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return {
          tag: element.tagName.toLowerCase(),
          testId: element.getAttribute('data-testid'),
          className: typeof element.className === 'string' ? element.className : '',
          parentClass: typeof element.parentElement?.className === 'string'
            ? element.parentElement.className
            : '',
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          position: style.position,
          cssWidth: style.width,
          maxWidth: style.maxWidth,
          leftCss: style.left,
          rightCss: style.right,
          padding: style.padding,
        };
      })
      .filter((item) => item.left < -1 || item.right > document.documentElement.clientWidth + 1)
      .slice(0, 12),
  }));
  expect(dimensions.scrollWidth, JSON.stringify(dimensions.offenders)).toBeLessThanOrEqual(
    dimensions.clientWidth,
  );
}

async function toastClearsEditorActions(page) {
  const toast = page.locator('.chakra-toast__inner').last();
  const actions = page.getByTestId('workspace-editor-actions');
  await expect(toast).toBeVisible();
  await expect(actions).toBeVisible();
  const [toastBox, actionsBox] = await Promise.all([
    toast.boundingBox(),
    actions.boundingBox(),
  ]);
  expect(toastBox).not.toBeNull();
  expect(actionsBox).not.toBeNull();
  const toastBottom = toastBox.y + toastBox.height;
  expect(
    toastBottom,
    JSON.stringify({ toastBottom, actionTop: actionsBox.y }),
  ).toBeLessThanOrEqual(actionsBox.y - 8);
}

test.describe('Work Hub live dev acceptance', () => {
  test.skip(!liveEnabled || !authToken, 'Requires an isolated dev user token and a live Compose stack.');

  test.beforeEach(async ({ context, page }) => {
    await authenticate(context);
    timingCollectors.set(page, collectLiveWorkTimings(page));
  });

  test.afterEach(async ({ page }, testInfo) => {
    const stop = timingCollectors.get(page);
    if (!stop) return;
    timingCollectors.delete(page);
    const artifactPath = testInfo.outputPath('bounded-work-timings.json');
    await fs.mkdir(path.dirname(artifactPath), { recursive: true });
    await fs.writeFile(artifactPath, JSON.stringify(stop()), 'utf8');
    await testInfo.attach('bounded-work-timings', {
      path: artifactPath, contentType: 'application/json',
    });
  });

  test('chat attachment persists in Library without passive sandbox activation', async ({ page }, testInfo) => {
    test.skip(!['chromium', 'mobile-chrome'].includes(testInfo.project.name), 'Qualified desktop/mobile live matrix.');
    if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1440, height: 900 });
    expect(page.viewportSize()).toEqual(testInfo.project.name === 'mobile-chrome'
      ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    const threadId = await createThread(page);
    const fileName = `chat-source-${testInfo.project.name}.txt`;
    const content = 'Материалы из чата.\nНачало, середина и конец синтетического источника.\n';
    const source = Buffer.from(content);
    const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
    let fileId;
    let workspaceMutations = 0;
    const observe = (request) => {
      const pathname = new URL(request.url()).pathname;
      if (request.method() === 'POST' && (
        pathname === `/api/chats/${threadId}/work/activate`
        || pathname === `/api/chats/${threadId}/work/upload`
        || pathname.startsWith(`/api/chats/${threadId}/work/library/`)
      )) workspaceMutations += 1;
    };
    page.on('request', observe);
    try {
      await page.goto(`/chat/${threadId}?surface=chat`, { waitUntil: 'domcontentloaded' });
      const uploadResponse = page.waitForResponse((response) => (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/chats/upload'
      ), { timeout: 60_000 });
      const chooserPromise = page.waitForEvent('filechooser');
      await page.getByRole('button', { name: 'Прикрепить файл', exact: true }).click();
      const chooser = await chooserPromise;
      await chooser.setFiles({ name: fileName, mimeType: 'text/plain', buffer: source });
      const uploaded = await uploadResponse;
      expect(uploaded.ok()).toBeTruthy();
      const attachment = await uploaded.json();
      fileId = attachment.file_id;
      expect(typeof fileId).toBe('string');
      expect(fileId.length).toBeGreaterThan(0);
      await page.getByRole('button', { name: 'Открыть работу с вложениями: 1', exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/chat/${threadId}\\?surface=work`));
      const hub = page.getByTestId('work-hub');
      await expect(hub).toHaveAttribute('data-workspace-state', 'absent');
      await openWorkbenchLibrary(page);
      const libraryItem = page.locator('[data-testid="work-library-file"]:visible').filter({ hasText: fileName });
      await expect(libraryItem).toBeVisible();
      await expect(libraryItem.getByText(/ · доступен$/)).toBeVisible();
      await noHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('live-chat-attachment-library.png'), fullPage: true });
      await page.reload();
      await expect(hub).toHaveAttribute('data-workspace-state', 'absent');
      await openWorkbenchLibrary(page);
      await expect(libraryItem).toBeVisible();
      expect(workspaceMutations).toBe(0);

      // Download the newly uploaded attachment through the actual Library
      // action after reload, before any sandbox exists. Keyboard activation
      // must not implicitly copy the source or provision a workspace.
      const downloadAction = libraryItem.locator(
        `a[href$="/api/service/files/v1/${fileId}/download"]`,
      );
      await expect(downloadAction).toBeVisible();
      const pendingDownload = page.waitForEvent('download', { timeout: 30_000 });
      await downloadAction.focus();
      await expect(downloadAction).toBeFocused();
      await downloadAction.press('Enter');
      const uiDownload = await pendingDownload;
      try {
        expect(await uiDownload.failure(), 'attachment_download_failed').toBeNull();
        expect(uiDownload.suggestedFilename(), 'attachment_download_name').toBe(fileName);
        const stream = await uiDownload.createReadStream();
        expect(stream, 'attachment_download_stream').not.toBeNull();
        const actualDigest = createHash('sha256');
        let size = 0;
        for await (const chunk of stream) {
          size += chunk.length;
          expect(size, 'attachment_download_size_limit').toBeLessThanOrEqual(source.length);
          actualDigest.update(chunk);
        }
        expect(size, 'attachment_download_size').toBe(source.length);
        expect(actualDigest.digest('hex'), 'attachment_download_digest').toBe(digest(source));
      } finally {
        await uiDownload.delete();
      }
      expect(workspaceMutations).toBe(0);
      await expect(hub).toHaveAttribute('data-workspace-state', 'absent');

      // Check MIME/disposition independently through the owner-checked route;
      // the keyboard interaction above supplies the browser-download evidence.
      const downloaded = await safeLiveRequest('download_file', () => page.request.get(
        `/api/service/files/v1/${fileId}/download`,
      ));
      expect(downloaded.ok()).toBeTruthy();
      // The backend applies the closed safe MIME/disposition contract even for
      // legacy storage objects.
      expect(downloaded.headers()['content-type']).toMatch(/^text\/plain(?:; charset=utf-8)?$/);
      expect(downloaded.headers()['content-disposition']).toMatch(/^attachment;/);
      expect(downloaded.headers()['content-disposition']).toContain(fileName);
      const bytes = await downloaded.body();
      expect(digest(bytes)).toBe(digest(source));

      await libraryItem.getByRole('button', { name: 'Создать и добавить', exact: true }).click();
      await expect(hub).toHaveAttribute('data-workspace-state', 'ready', { timeout: 60_000 });
      await closeWorkbenchLibrary(page);
      if (testInfo.project.name === 'mobile-chrome') {
        await page.getByRole('tab', { name: 'Файлы', exact: true }).click();
      }
      const item = page.locator(`[data-testid="workspace-file"][data-workspace-path="${fileName}"]`);
      await item.click();
      await expect(page.getByRole('textbox', { name: `Содержимое ${fileName}` })).toHaveValue(
        content, { timeout: 20_000 },
      );
      await noHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('live-chat-attachment-copy.png'), fullPage: true });
    } finally {
      page.off('request', observe);
      try {
        if (fileId) {
          const removed = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
          expect(removed.ok()).toBeTruthy();
        }
      } finally {
        await removeThread(page, threadId);
      }
    }
  });

  test('owned ZIP Work intake, download and repeated copy preserve edited content', async ({ page }, testInfo) => {
    test.skip(!['chromium', 'mobile-chrome'].includes(testInfo.project.name), 'Qualified desktop/mobile live matrix.');
    if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1440, height: 900 });
    const threadId = await createThread(page);
    const fileName = `owned-archive-${testInfo.project.name}.zip`;
    const extractedPath = `${fileName.slice(0, -4)}/content/notes.txt`;
    // Fixed, synthetic, stored ZIP: content/notes.txt + references.bib.
    // No fixture paths, credentials or user materials are bundled.
    const source = Buffer.from(
      'UEsDBBQAAAAAAAAAIQBt9VGfFAAAABQAAAARAAAAY29udGVudC9ub3Rlcy50eHRBcmNoaXZlIHNvdXJjZSB0ZXh0ClBLAwQUAAAAAAAAACEA2+4yzykAAAApAAAADgAAAHJlZmVyZW5jZXMuYmliQG1pc2N7Zml4dHVyZSwgdGl0bGU9e1N5bnRoZXRpYyBzb3VyY2V9fQpQSwECFAAUAAAAAAAAACEAbfVRnxQAAAAUAAAAEQAAAAAAAAAAAAAAgAEAAAAAY29udGVudC9ub3Rlcy50eHRQSwECFAAUAAAAAAAAACEA2+4yzykAAAApAAAADgAAAAAAAAAAAAAAgAFDAAAAcmVmZXJlbmNlcy5iaWJQSwUGAAAAAAIAAgB7AAAAmAAAAAAA',
      'base64',
    );
    let fileId;
    let zipStage = 'open';
    let copyStatus = null;
    try {
      await openWork(page, threadId);
      const hub = page.getByTestId('work-hub');
      await expect(hub).toHaveAttribute('data-workspace-state', 'absent');
      // Work intake persists the source without paid repository analysis.
      // Chat ZIP intake has a separate Graphify cost boundary and is not
      // silently substituted into this zero-inference acceptance scenario.
      zipStage = 'upload';
      await upload(page, fileName, source, (id) => { fileId = id; }, 'application/zip');
      zipStage = 'download';
      await openWorkbenchLibrary(page);
      const libraryItem = page.locator('[data-testid="work-library-file"]:visible').filter({ hasText: fileName });
      await expect(libraryItem).toBeVisible();
      const downloadPromise = page.waitForEvent('download', { timeout: 30_000 });
      const downloadAction = libraryItem.locator(`a[href$="/api/service/files/v1/${fileId}/download"]`);
      await downloadAction.focus();
      await expect(downloadAction).toBeFocused();
      await downloadAction.press('Enter');
      const download = await downloadPromise;
      try {
        expect(await download.failure(), 'zip_download_failed').toBeNull();
        expect(download.suggestedFilename()).toBe(fileName);
        const stream = await download.createReadStream();
        expect(stream).not.toBeNull();
        const hash = createHash('sha256');
        let size = 0;
        for await (const chunk of stream) {
          size += chunk.length;
          expect(size).toBeLessThanOrEqual(source.length);
          hash.update(chunk);
        }
        expect(size).toBe(source.length);
        expect(hash.digest('hex')).toBe(createHash('sha256').update(source).digest('hex'));
      } finally {
        await download.delete();
      }
      await expect(hub).toHaveAttribute('data-workspace-state', 'ready', { timeout: 60_000 });
      zipStage = 'extracted_read';
      const openFiles = async () => {
        await closeWorkbenchLibrary(page);
        if (testInfo.project.name === 'mobile-chrome') {
          await page.getByRole('tab', { name: 'Файлы', exact: true }).click();
        }
      };
      await openFiles();
      const bibliographyPath = `${fileName.slice(0, -4)}/references.bib`;
      await (await revealWorkspaceFile(page, bibliographyPath)).click();
      await expect(page.getByRole('textbox', { name: `Содержимое ${bibliographyPath}` })).toHaveValue(
        '@misc{fixture, title={Synthetic source}}\n',
      );
      await (await revealWorkspaceFile(page, extractedPath)).click();
      const editor = page.getByRole('textbox', { name: `Содержимое ${extractedPath}` });
      await expect(editor).toHaveValue('Archive source text\n');
      await editor.fill('Preserved user edit\n');
      zipStage = 'save';
      await editor.press('Control+s');
      await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
      await openWorkbenchLibrary(page);
      zipStage = 'repeat_copy';
      const copied = page.waitForResponse((response) => (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/chats/${threadId}/work/library/${fileId}/copy`
      ));
      await libraryItem.getByRole('button', { name: 'Добавить в рабочее место', exact: true }).click();
      const copyResponse = await copied;
      copyStatus = copyResponse.status();
      expect(copyResponse.ok()).toBeTruthy();
      expect((await copyResponse.json()).outcome).toBe('kept');
      const read = await safeLiveRequest('read_file', () => page.request.post(
        `/api/chats/${threadId}/workspace/file`, { data: { path: extractedPath } },
      ));
      expect(read.ok()).toBeTruthy();
      expect((await read.json()).content).toBe('Preserved user edit\n');
      zipStage = 'reload';
      await page.reload();
      await openFiles();
      await (await revealWorkspaceFile(page, extractedPath)).click();
      await expect(editor).toHaveValue('Preserved user edit\n');
      await noHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('live-zip-edit-preserved.png') });
      zipStage = 'complete';
    } finally {
      const reportPath = testInfo.outputPath('bounded-zip-stage.json');
      await fs.mkdir(path.dirname(reportPath), { recursive: true });
      await fs.writeFile(reportPath, JSON.stringify({ stage: zipStage, copyStatus }), 'utf8');
      await testInfo.attach('bounded-zip-stage', { path: reportPath, contentType: 'application/json' });
      try {
        if (fileId) {
          const removed = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
          expect(removed.ok()).toBeTruthy();
        }
      } finally {
        await removeThread(page, threadId);
      }
    }
  });

  test('leaving Work during acquisition releases the real lease and permits explicit recovery', async ({ page }, testInfo) => {
    if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1440, height: 900 });
    const threadId = await createThread(page);
    let fileId;
    let finishAcquire;
    const responseGate = new Promise((resolve) => { finishAcquire = resolve; });
    let accepted = false;
    let holdResponse = true;
    const acquirePattern = `**/api/chats/${threadId}/workspace/leases/acquire`;
    try {
      await openWork(page, threadId);
      await upload(page, 'lease-recovery.txt', 'lease recovery fixture\n', (id) => { fileId = id; });
      await page.route(acquirePattern, async (route) => {
        const response = await safeLiveRequest('lease_acquire', () => route.fetch());
        expect(response.ok()).toBeTruthy();
        accepted = true;
        if (holdResponse) await responseGate;
        await route.fulfill({ response });
      });
      await page.locator('[data-testid="workspace-file"][data-workspace-path="lease-recovery.txt"]').click();
      await expect.poll(() => accepted).toBe(true);
      await page.getByRole('button', { name: 'Чат', exact: true }).click();
      await expect(page).not.toHaveURL(/surface=work/);
      const released = page.waitForResponse((response) => (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/chats/${threadId}/workspace/leases/release`
      ));
      holdResponse = false;
      finishAcquire();
      expect((await released).ok()).toBeTruthy();
      await page.getByRole('button', { name: 'Работа', exact: true }).click();
      const editor = page.getByRole('textbox', { name: 'Содержимое lease-recovery.txt' });
      await expect(editor).toHaveValue('lease recovery fixture\n');
      await expect(editor).toHaveAttribute('readonly', '');
      await page.getByRole('button', { name: 'Получить право', exact: true }).click();
      await expect(editor).not.toHaveAttribute('readonly', '');
      await editor.fill('saved after explicit lease recovery\n');
      await editor.press('Control+s');
      await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
      const read = await safeLiveRequest('read_file', () => page.request.post(
        `/api/chats/${threadId}/workspace/file`, { data: { path: 'lease-recovery.txt' } },
      ));
      expect(read.ok()).toBeTruthy();
      expect((await read.json()).content).toBe('saved after explicit lease recovery\n');
      await noHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('live-lease-recovery.png') });
    } finally {
      finishAcquire();
      await page.unroute(acquirePattern);
      if (fileId) {
        const deleted = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
        expect(deleted.ok()).toBeTruthy();
      }
      await removeThread(page, threadId);
    }
  });

  test('new edits during an acknowledged server write remain protected until a second save', async ({ page }, testInfo) => {
    if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1440, height: 900 });
    const threadId = await createThread(page);
    const fileName = 'save-race.txt';
    let fileId;
    let releaseResponse;
    const responseGate = new Promise((resolve) => { releaseResponse = resolve; });
    let committed = false;
    let held = false;
    await page.route(`**/api/chats/${threadId}/workspace/write`, async (route) => {
      const response = await safeLiveRequest('write_response', () => route.fetch());
      if (!held) {
        held = true;
        committed = response.ok();
        await responseGate;
      }
      await route.fulfill({ response });
    });
    try {
      await openWork(page, threadId);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
      await upload(page, fileName, 'initial synthetic text\n', (savedId) => { fileId = savedId; });
      await page.locator(`[data-testid="workspace-file"][data-workspace-path="${fileName}"]`).click();
      const editor = page.getByRole('textbox', { name: `Содержимое ${fileName}` });
      await editor.fill('submitted synthetic text\n');
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect.poll(() => committed).toBe(true);
      await editor.fill('newer unsent synthetic text\n');
      const persisted = await safeLiveRequest('read_file', () => page.request.post(`/api/chats/${threadId}/workspace/file`, { data: { path: fileName } }));
      expect(persisted.ok()).toBeTruthy();
      expect((await persisted.json()).content).toBe('submitted synthetic text\n');
      releaseResponse();
      await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeEnabled();
      await expect(editor).toHaveValue('newer unsent synthetic text\n');
      await page.getByRole('button', { name: 'Чат', exact: true }).click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByRole('button', { name: 'Продолжить редактирование' })).toBeFocused();
      await dialog.getByRole('button', { name: 'Продолжить редактирование' }).click();
      await expect(editor).toBeFocused();
      await expect(editor).toHaveValue('newer unsent synthetic text\n');
      await editor.press('Control+s');
      await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
      const saved = await safeLiveRequest('read_file', () => page.request.post(`/api/chats/${threadId}/workspace/file`, { data: { path: fileName } }));
      expect(saved.ok()).toBeTruthy();
      expect((await saved.json()).content).toBe('newer unsent synthetic text\n');
      await page.reload();
      await page.locator(`[data-testid="workspace-file"][data-workspace-path="${fileName}"]`).click();
      await expect(editor).toHaveValue('newer unsent synthetic text\n');
      await noHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('live-save-race.png'), fullPage: true });
    } finally {
      releaseResponse();
      await removeThread(page, threadId);
      if (fileId) {
        const removed = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
        expect(removed.ok()).toBeTruthy();
      }
    }
  });

  test('passive view, direct intake, edit and responsive layout', async ({ page }, testInfo) => {
    if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1440, height: 900 });
    const threadId = await createThread(page);
    const fileName = `brief-${testInfo.project.name}.txt`;
    let fileId;
    try {
      await openWork(page, threadId);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');

      await upload(page, fileName, 'initial synthetic content\n', (savedId) => { fileId = savedId; });
      const fileItem = page.locator(
        `[data-testid="workspace-file"][data-workspace-path="${fileName}"]`,
      );
      await fileItem.click();
      const editor = page.getByRole('textbox', { name: `Содержимое ${fileName}` });
      await expect(editor).toBeEnabled();
      await editor.fill('initial synthetic content\nuser edit\n');
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(editor).toHaveValue('initial synthetic content\nuser edit\n');
      await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
      // Observe transient feedback at acknowledgement, before unrelated live
      // REST latency can consume its lifetime. Persistence is checked below.
      await toastClearsEditorActions(page);
      const persisted = await safeLiveRequest('read_file', () => page.request.post(
        `/api/chats/${threadId}/workspace/file`, { data: { path: fileName } },
      ));
      expect(persisted.ok()).toBeTruthy();
      expect((await persisted.json()).content).toBe('initial synthetic content\nuser edit\n');
      await noHorizontalOverflow(page);
      await expect.poll(async () => {
        const actions = await page.getByTestId('workspace-editor-actions').boundingBox();
        return actions
          ? Math.abs(page.viewportSize().height - actions.y - actions.height)
          : Infinity;
      }).toBeLessThanOrEqual(2);

      const screenshotName = testInfo.project.name === 'mobile-chrome'
        ? 'live-work-hub-mobile.png'
        : 'live-work-hub-desktop.png';
      await page.screenshot({ path: testInfo.outputPath(screenshotName), fullPage: true });
    } finally {
      try {
        if (fileId) {
          const removed = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
          expect(removed.ok()).toBeTruthy();
        }
      } finally {
        await removeThread(page, threadId);
      }
    }
  });

  test('lease collision and revision conflict keep the dirty draft', async ({ browser, page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'Two-context conflict acceptance runs on desktop.');
    await page.setViewportSize({ width: 1440, height: 900 });
    const threadId = await createThread(page);
    const secondContext = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } });
    await authenticate(secondContext);
    const secondPage = await secondContext.newPage();
    const stopSecondTimings = collectLiveWorkTimings(secondPage);
    const fileIds = [];
    const draft = 'draft retained after revision conflict\n';
    try {
      await openWork(page, threadId);
      await upload(page, 'lease.txt', 'base revision\n', (fileId) => fileIds.push(fileId));
      await page.locator('[data-testid="workspace-file"][data-workspace-path="lease.txt"]').click();
      const editor = page.getByRole('textbox', { name: 'Содержимое lease.txt' });
      await expect(editor).toBeEnabled();
      await editor.fill(draft);

      await openWork(secondPage, threadId);
      await secondPage.locator(
        '[data-testid="workspace-file"][data-workspace-path="lease.txt"]',
      ).click();
      await expect(
        secondPage.getByRole('textbox', { name: 'Содержимое lease.txt' }),
      ).toHaveAttribute('readonly', '');
      await expect(secondPage.getByText('Файл уже редактируется в другом окне.')).toBeVisible();

      await upload(secondPage, 'concurrent.txt', 'concurrent revision\n', (fileId) => fileIds.push(fileId));
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(page.getByText('Версия файла изменилась')).toBeVisible();
      await expect(editor).toHaveValue(draft);
    } finally {
      const secondTimingsPath = testInfo.outputPath('bounded-second-context-timings.json');
      await fs.mkdir(path.dirname(secondTimingsPath), { recursive: true });
      await fs.writeFile(secondTimingsPath, JSON.stringify(stopSecondTimings()), 'utf8');
      await testInfo.attach('bounded-second-context-timings', {
        path: secondTimingsPath, contentType: 'application/json',
      });
      await secondContext.close();
      await removeThread(page, threadId);
      for (const fileId of fileIds) {
        const removed = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
        expect(removed.ok()).toBeTruthy();
      }
    }
  });

  test('history diff and confirmed revert restore the imported revision', async ({ page }, testInfo) => {
    if (testInfo.project.name === 'chromium') await page.setViewportSize({ width: 1440, height: 900 });
    const threadId = await createThread(page);
    const fileName = 'history-cycle.txt';
    const original = 'original history fixture\n';
    const edited = 'edited history fixture\n';
    let fileId;
    try {
      await openWork(page, threadId);
      await upload(page, fileName, original, (id) => { fileId = id; });
      const item = page.locator(`[data-testid="workspace-file"][data-workspace-path="${fileName}"]`);
      await item.click();
      const editor = page.getByRole('textbox', { name: `Содержимое ${fileName}` });
      await expect(editor).toHaveValue(original);
      await editor.fill(edited);
      await editor.press('Control+s');
      await expect(page.getByText('Сохранено.', { exact: true })).toBeVisible();
      if (testInfo.project.name === 'mobile-chrome') {
        await page.getByRole('tab', { name: 'Контекст', exact: true }).click();
      }
      await page.getByRole('tab', { name: 'История', exact: true }).click();
      const historyPanel = page.locator('[role="tabpanel"]:visible').filter({
        has: page.getByText('Импорт файла', { exact: true }),
      });
      await expect(historyPanel.getByText('Правка пользователя', { exact: true })).toBeVisible({ timeout: 20_000 });
      const importCard = historyPanel.getByText('Импорт файла', { exact: true }).locator('..');
      const diffResponse = page.waitForResponse((response) => (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/chats/${threadId}/workspace/diff`
      ));
      await importCard.getByRole('button', { name: 'Показать diff', exact: true }).click();
      const diff = await diffResponse;
      expect(diff.ok()).toBeTruthy();
      const diffText = (await diff.json()).diff;
      expect(diffText).toContain(original.trim());
      expect(diffText).toContain(edited.trim());
      if (testInfo.project.name === 'mobile-chrome') {
        await page.getByRole('tab', { name: 'Файлы', exact: true }).click();
      }
      await expect(page.getByText('Изменения перед откатом', { exact: true })).toBeVisible();
      // Preview alone is read-only: the saved server version must remain edited.
      const before = await safeLiveRequest('read_file', () => page.request.post(
        `/api/chats/${threadId}/workspace/file`, { data: { path: fileName } },
      ));
      expect(before.ok()).toBeTruthy();
      expect((await before.json()).content).toBe(edited);
      const reverted = page.waitForResponse((response) => (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/chats/${threadId}/workspace/revert`
      ));
      await page.getByRole('button', { name: 'Подтвердить откат', exact: true }).click();
      expect((await reverted).ok()).toBeTruthy();
      await expect(editor).not.toBeVisible();
      await item.click();
      await expect(editor).toHaveValue(original);
      const restored = await safeLiveRequest('read_file', () => page.request.post(
        `/api/chats/${threadId}/workspace/file`, { data: { path: fileName } },
      ));
      expect(restored.ok()).toBeTruthy();
      expect((await restored.json()).content).toBe(original);
      await page.reload();
      await item.click();
      await expect(editor).toHaveValue(original);
      await noHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('live-history-revert.png'), fullPage: true });
    } finally {
      try {
        if (fileId) {
          const removed = await safeLiveRequest('delete_file', () => page.request.delete(`/api/service/files/v1/delete/${fileId}`));
          expect(removed.ok()).toBeTruthy();
        }
      } finally {
        await removeThread(page, threadId);
      }
    }
  });

  test('trusted document profile builds a PDF preview with validated bytes', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'The compiler acceptance runs once on desktop.');
    test.setTimeout(240_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    expect(await page.evaluate(() => navigator.pdfViewerEnabled)).toBe(true);
    const threadId = await createThread(page);
    try {
      await openWork(page, threadId);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');
      await page.getByTestId('work-activate').click();
      await expect(page.getByTestId('work-hub')).toHaveAttribute(
        'data-workspace-state',
        'ready',
        { timeout: 60_000 },
      );

      // PDF is now a peer thread surface, not a hidden Work context tab.
      await page.getByRole('button', { name: 'PDF', exact: true }).click();
      const panel = page.getByTestId('pdf-studio');
      await expect(panel).toBeVisible();
      await panel.getByRole('button', { name: 'Создать проект' }).click();
      await panel.getByRole('button', { name: 'Новое содержание без ИИ', exact: true }).click();
      await page.getByRole('alertdialog').getByRole('button', { name: 'Создать новое содержание', exact: true }).click();
      const title = panel.getByRole('textbox', { name: 'Название документа', exact: true });
      await expect(title).toBeVisible({ timeout: 30_000 });
      await title.fill('Обзор методов машинного обучения');
      await panel.getByRole('textbox', { name: /^Текст блока / }).first().fill(
        'Синтетический документ для проверки редактора и PDF-превью. '
        + 'Этот материал проверяет сохранение исходников и компиляцию, а не научные утверждения.',
      );
      const save = panel.getByRole('button', { name: 'Сохранить', exact: true });
      await save.click();
      await expect(save).toBeDisabled({ timeout: 30_000 });
      await panel.getByRole('button', { name: 'Собрать черновик' }).click();
      await expect(panel.getByText('Черновик готов', { exact: true })).toBeVisible({
        timeout: 180_000,
      });
      await panel.getByRole('button', { name: 'Открыть PDF' }).click();
      const preview = panel.locator('iframe[title="Предпросмотр PDF"]');
      await expect(preview).toBeVisible();
      await preview.scrollIntoViewIfNeeded();
      await expect(panel.frameLocator('iframe[title="Предпросмотр PDF"]').locator('embed')).toBeVisible();
      const previewBox = await preview.boundingBox();
      expect(previewBox.y).toBeGreaterThanOrEqual(0);
      // Fractional CSS layout can round the panel edge by a subpixel; use the
      // same one-pixel geometry tolerance as the overflow checks above.
      expect(previewBox.y + previewBox.height).toBeLessThanOrEqual(page.viewportSize().height + 1);
      const facts = await preview.evaluate(async (element) => {
        try {
          const response = await fetch(element.src);
          const blob = await response.blob();
          if (blob.size > 16 * 1024 * 1024) throw new Error('oversized_fixture');
          return {
            ok: response.ok,
            mime: blob.type,
            size: blob.size,
            pdfHeader: (await blob.slice(0, 5).text()) === '%PDF-',
            pdfEnd: (await blob.slice(-4096).text()).includes('%%EOF'),
            sha256: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())))
              .map((byte) => byte.toString(16).padStart(2, '0')).join(''),
          };
        } catch {
          throw new Error('live_pdf_preview_unavailable');
        }
      });
      expect(facts.ok).toBe(true);
      expect(facts.mime).toBe('application/pdf');
      expect(facts.size).toBeGreaterThan(100);
      expect(facts.pdfHeader).toBe(true);
      expect(facts.pdfEnd).toBe(true);
      expect(facts.sha256).toMatch(/^[a-f0-9]{64}$/);
      await noHorizontalOverflow(page);
      await page.screenshot({
        path: testInfo.outputPath('live-document-forge-preview.png'),
        fullPage: true,
      });
    } finally {
      await removeThread(page, threadId);
    }
  });
});
