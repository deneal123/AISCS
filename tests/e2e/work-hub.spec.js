const { test, expect } = require('@playwright/test');

const THREAD_ID = 'work-hub-contract-thread';

function snapshot({ active, uploaded, documentReady, vendorAvailable, vendorApplied }) {
  const entries = [];
  if (uploaded) entries.push({ path: 'brief.txt', type: 'file', size: 18 });
  if (documentReady) {
    entries.push(
      { path: 'documents/paper/document.toml', type: 'file', size: 180 },
      { path: 'documents/paper/main.tex', type: 'file', size: 320 },
    );
  }
  const libraryItems = [];
  if (uploaded) {
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
    activationCalls: 0,
    leaseReleases: 0,
    fileContent: 'synthetic work contract',
    documentReady: false,
    vendorAvailable: false,
    vendorApplied: false,
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
      await route.fulfill({ json: snapshot(state) });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work/activate` && method === 'POST') {
      state.activationCalls += 1;
      state.active = true;
      await route.fulfill({ json: snapshot(state) });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work/upload` && method === 'POST') {
      state.active = true;
      state.uploaded = true;
      await route.fulfill({
        json: {
          outcome: 'imported',
          revision: 'revision-2',
          library_file: {
            file_id: 'file-opaque-1',
            name: 'brief.txt',
            file_type: 'text/plain',
            availability: 'ready',
          },
        },
      });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/leases/acquire` && method === 'POST') {
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
      await route.fulfill({ json: { revision: 'revision-3', fence: 7 } });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/workspace/issues`) {
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
  await expect.poll(() => page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }))).toEqual(expect.objectContaining({ client: expect.any(Number), scroll: expect.any(Number) }));
  const dimensions = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client);
}

test.describe('Work Hub composition contract', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(
      !['chromium', 'tablet', 'mobile-chrome'].includes(testInfo.project.name),
      'The mandatory Work Hub gate covers desktop, tablet and mobile Chromium.',
    );
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

  test('installs a Library vendor kit through the guarded project action', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'Document vendor flow runs once on desktop.');
    const state = await installWorkApi(page);
    state.active = true;
    state.documentReady = true;
    state.vendorAvailable = true;
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });

    await page.getByRole('tab', { name: 'PDF' }).click();
    const documentPanel = page.locator('[role="tabpanel"]:visible');
    await expect(documentPanel.getByText('Шаблон издателя', { exact: true })).toBeVisible();
    await documentPanel.getByRole('button', { name: 'Добавить в проект' }).click();

    await expect.poll(() => state.vendorApplied).toBe(true);
    await expect(documentPanel.getByText('journal-kit', { exact: true })).toBeVisible();
    await expect(documentPanel.getByText(/1\.0 · изолирован/)).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test('dirty navigation is cancelled or confirmed without losing control of the lease', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium', 'The shared router guard is viewport-independent.');
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
