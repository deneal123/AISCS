const { test, expect } = require('@playwright/test');
const { installLibraryApi, THREAD } = require('./helpers/libraryApi');
const { openWorkbenchLibrary, closeWorkbenchLibrary } = require('./helpers/workbenchLibrary');

test.use({ serviceWorkers: 'block' });

const selection = name => ({ name, mimeType: 'text/plain', buffer: Buffer.from('synthetic upload fixture') });
const uploadRoute = `**/api/chats/${THREAD}/work/library/upload`;
const intentOf = request => request.postDataBuffer().toString('utf8')
  .match(/name="upload_intent_id"\r\n\r\n([^\r\n]+)/)?.[1];

async function passive(page, state) {
  expect(state.mutations).toEqual([]);
  await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}$`));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test('cancelled Library upload reconciles committed bytes and reuses its intent only on explicit retry', async ({ page }) => {
  const state = await installLibraryApi(page);
  const intents = [];
  const item = { file_id: 'cancel-file', name: 'cancel.txt', availability: 'ready', file_type: 'text/plain' };
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route(uploadRoute, async route => {
    intents.push(intentOf(route.request()));
    if (intents.length === 1) {
      state.items.unshift(item);
      await held;
      try { await route.abort('aborted'); } catch { /* Client already cancelled this request. */ }
    } else await route.fulfill({ json: { outcome: 'library_uploaded', workspace_status: 'not_requested', file: item } });
  });
  try {
    const library = await openWorkbenchLibrary(page);
    await library.getByTestId('work-upload-input').setInputFiles(selection(item.name));
    await expect.poll(() => intents.length).toBe(1);
    const cancel = library.getByRole('button', { name: 'Отменить', exact: true });
    await cancel.focus(); await cancel.press('Enter');
    await expect(library.getByText('Загрузка отменена. Проверьте библиотеку перед повтором.', { exact: true })).toBeVisible();
    release();
    await expect(library.getByRole('link', { name: 'Скачать cancel.txt', exact: true })).toBeVisible();
    const retry = library.getByRole('button', { name: 'Проверить и повторить', exact: true });
    await expect(retry).toBeFocused();
    await retry.focus(); await retry.press('Enter');
    await expect.poll(() => intents.length).toBe(2);
    await expect(retry).toHaveCount(0);
    expect(intents[0]).toMatch(/^[\da-f-]{36}$/);
    expect(intents[1]).toBe(intents[0]);
    await passive(page, state);
  } finally { release(); }
});

test('unknown Library upload retains the selected file through close/reopen without automatic replay', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  const state = await installLibraryApi(page);
  const intents = [];
  await page.route(uploadRoute, async route => {
    intents.push(intentOf(route.request()));
    await route.fulfill({ status: 503, json: { detail: 'private-upload-body' } });
  });
  const library = await openWorkbenchLibrary(page);
  await library.getByTestId('work-upload-input').setInputFiles(selection('retry.txt'));
  const retry = library.getByRole('button', { name: 'Проверить и повторить', exact: true });
  await expect(retry).toBeVisible();
  await closeWorkbenchLibrary(page);
  await openWorkbenchLibrary(page);
  const selected = library.getByText('retry.txt', { exact: true });
  await expect(selected).toBeVisible();
  expect(await selected.evaluate(node => node.clientWidth >= node.scrollWidth)).toBe(true);
  expect(intents).toHaveLength(1);
  await retry.focus(); await retry.press('Enter');
  await expect.poll(() => intents.length).toBe(2);
  await expect(retry).toBeVisible();
  expect(intents[1]).toBe(intents[0]);
  await expect(page.getByText('private-upload-body', { exact: true })).toHaveCount(0);
  await passive(page, state);
});

test('changed-file conflict explains reselection and a newly chosen file receives a new intent', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  const state = await installLibraryApi(page);
  const intents = [];
  await page.route(uploadRoute, async route => {
    intents.push(intentOf(route.request()));
    if (intents.length === 1) await route.fulfill({ status: 409, json: { detail: 'upload_intent_conflict' } });
    else {
      const item = { file_id: 'changed-file', name: 'different.txt', availability: 'ready' };
      state.items.unshift(item);
      await route.fulfill({ json: { outcome: 'library_uploaded', workspace_status: 'not_requested', file: item } });
    }
  });
  const library = await openWorkbenchLibrary(page);
  await library.getByTestId('work-upload-input').setInputFiles(selection('changed.txt'));
  await expect(library.getByText('Содержимое файла отличается от предыдущей попытки. Выберите файл заново.', { exact: true })).toBeVisible();
  await expect(library.getByRole('button', { name: 'Проверить и повторить', exact: true })).toHaveCount(0);
  await expect(library.getByText('changed.txt', { exact: true })).toBeVisible();
  await library.getByTestId('work-upload-input').setInputFiles(selection('different.txt'));
  await expect(library.getByRole('link', { name: 'Скачать different.txt', exact: true })).toBeVisible();
  expect(intents).toHaveLength(2);
  expect(intents[1]).not.toBe(intents[0]);
  await passive(page, state);
});

test('Library upload feedback leaves download and copy reachable in a short narrow viewport', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 550 });
  const state = await installLibraryApi(page);
  await page.route(uploadRoute, async route => {
    const item = { file_id: 'notice-file', name: 'notice.txt', availability: 'ready', file_type: 'text/plain' };
    state.items = [item];
    await route.fulfill({ json: { outcome: 'library_uploaded', workspace_status: 'not_requested', file: item } });
  });
  const library = await openWorkbenchLibrary(page);
  await library.getByTestId('work-upload-input').setInputFiles(selection('notice.txt'));
  const item = library.getByTestId('work-library-file').filter({ hasText: 'notice.txt' });
  const download = item.getByRole('link', { name: 'Скачать notice.txt', exact: true });
  const copy = item.getByRole('button', { name: 'Создать и добавить', exact: true });
  await expect(download).toBeVisible();
  const toast = page.locator('.chakra-toast__inner').last();
  await expect(toast).toBeVisible();
  await toast.hover();
  await download.scrollIntoViewIfNeeded();
  await expect.poll(async () => {
    const [notice, actions] = await Promise.all([toast.boundingBox(), item.locator('[data-toast-protected-actions]').boundingBox()]);
    return Boolean(notice && actions && (
      notice.y + notice.height + 8 <= actions.y || actions.y + actions.height + 8 <= notice.y
      || notice.x + notice.width + 8 <= actions.x || actions.x + actions.width + 8 <= notice.x));
  }).toBe(true);
  await download.click({ trial: true }); await download.focus(); await expect(download).toBeFocused();
  await copy.click({ trial: true }); await copy.focus(); await expect(copy).toBeFocused();
  await page.screenshot({ path: info.outputPath('library-upload-feedback.png'), animations: 'disabled' });
  await passive(page, state);
});
