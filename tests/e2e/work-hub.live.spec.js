const { test, expect } = require('@playwright/test');

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
  const response = await page.request.post('/api/chats/', {
    data: { title: `S28 Work Hub ${Date.now()}` },
  });
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  expect(typeof payload.thread_id).toBe('string');
  return payload.thread_id;
}

async function removeThread(page, threadId) {
  await page.request.delete(`/api/chats/${threadId}`).catch(() => {});
}

async function openWork(page, threadId) {
  await page.goto(`/chat/${threadId}?surface=work`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('work-hub')).toBeVisible();
}

async function upload(page, name, content) {
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
  }).then((request) => {
    throw new Error(`work upload request failed: ${request.failure()?.errorText || 'unknown'}`);
  });
  await page.getByTestId('work-upload-input').setInputFiles({
    name,
    mimeType: 'text/plain',
    buffer: Buffer.from(content),
  });
  const request = await requestPromise;
  expect(new URL(request.url()).pathname).toMatch(/\/work\/upload$/);
  const response = await Promise.race([responsePromise, failurePromise]);
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(['imported', 'kept']).toContain(result.outcome);
  await expect(page.getByTestId('work-hub')).toHaveAttribute(
    'data-workspace-state',
    'ready',
    { timeout: 20_000 },
  );
  await expect(
    page.locator(`[data-testid="workspace-file"][data-workspace-path="${name}"]`),
  ).toBeVisible();
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

  test.beforeEach(async ({ context }) => authenticate(context));

  test('passive view, direct intake, edit and responsive layout', async ({ page }, testInfo) => {
    const threadId = await createThread(page);
    const fileName = `brief-${testInfo.project.name}.txt`;
    try {
      await openWork(page, threadId);
      await expect(page.getByTestId('work-hub')).toHaveAttribute('data-workspace-state', 'absent');

      await upload(page, fileName, 'initial synthetic content\n');
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
      await noHorizontalOverflow(page);
      await toastClearsEditorActions(page);

      const screenshotName = testInfo.project.name === 'mobile-chrome'
        ? 'live-work-hub-mobile.png'
        : 'live-work-hub-desktop.png';
      await page.screenshot({ path: `../tmp_e2e/${screenshotName}`, fullPage: true });
    } finally {
      await removeThread(page, threadId);
    }
  });

  test('lease collision and revision conflict keep the dirty draft', async ({ browser, page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'Two-context conflict acceptance runs on desktop.');
    const threadId = await createThread(page);
    const secondContext = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } });
    await authenticate(secondContext);
    const secondPage = await secondContext.newPage();
    const draft = 'draft retained after revision conflict\n';
    try {
      await openWork(page, threadId);
      await upload(page, 'lease.txt', 'base revision\n');
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

      await upload(secondPage, 'concurrent.txt', 'concurrent revision\n');
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(page.getByText('Версия файла изменилась')).toBeVisible();
      await expect(editor).toHaveValue(draft);
    } finally {
      await secondContext.close();
      await removeThread(page, threadId);
    }
  });

  test('trusted document profile builds a readable PDF preview', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'The compiler acceptance runs once on desktop.');
    test.setTimeout(240_000);
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

      await page.getByRole('tab', { name: 'PDF' }).click();
      const panel = page.locator('[role="tabpanel"]:visible');
      await panel.getByRole('button', { name: 'Создать проект' }).click();
      await expect(panel.getByText('Проект', { exact: true })).toBeVisible({ timeout: 30_000 });
      await panel.getByRole('button', { name: 'Собрать черновик' }).click();
      await expect(panel.getByText('Черновик готов', { exact: true })).toBeVisible({
        timeout: 180_000,
      });
      await panel.getByRole('button', { name: 'Открыть PDF' }).click();
      await expect(panel.locator('iframe[title="Предпросмотр PDF"]')).toBeVisible();
      await noHorizontalOverflow(page);
      await page.screenshot({
        path: '../tmp_e2e/live-document-forge-preview.png',
        fullPage: true,
      });
    } finally {
      await removeThread(page, threadId);
    }
  });
});
