const { test, expect } = require('@playwright/test');
const { createServer } = require('http');
const axe = require('axe-core');
const { installLibraryApi, THREAD } = require('./helpers/libraryApi');
const { openWorkbenchLibrary, triggerWorkbenchLibrary } = require('./helpers/workbenchLibrary');

test.use({ serviceWorkers: 'block' });

for (const width of [320, 393]) test(`mobile regression: Library long filename wraps and actions stay separated ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 640 });
  const state = await installLibraryApi(page);
  const longName = `Ранее загруженный файл ${'d8d38d9b'.repeat(12)}.pdf`;
  state.items = [{ file_id: 'file-opaque-1', name: longName, availability: 'ready' }];
  const library = await openWorkbenchLibrary(page);
  const item = library.getByTestId('work-library-file');
  const name = item.getByText(longName, { exact: true });
  await expect(name).toBeVisible();
  expect(await name.evaluate(element => element.scrollHeight <= element.clientHeight && element.scrollWidth <= element.clientWidth)).toBe(true);
  const download = await item.getByRole('link', { name: `Скачать ${longName}`, exact: true }).boundingBox();
  const copy = await item.getByRole('button', { name: 'Создать и добавить', exact: true }).boundingBox();
  const horizontal = copy.x - download.x - download.width;
  const vertical = copy.y - download.y - download.height;
  expect(Math.max(horizontal, vertical)).toBeGreaterThanOrEqual(8);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(state.mutations).toEqual([]);
  await page.screenshot({ path: info.outputPath(`mobile-library-${width}.png`) });
});

async function expectPassive(page, state) {
  expect(state.mutations).toEqual([]);
  await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}$`));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test('cold Library chunk loading can close and reopen without a surface change or mutation', async ({ page }, info) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let chunks = 0;
  await page.route('**/static/js/*.chunk.js', async route => {
    const response = await route.fetch(); const body = await response.body();
    if (/['"]work-hub['"]/.test(body.toString('utf8'))) { chunks += 1; await held; }
    await route.fulfill({ response, body });
  });
  try {
    const state = await installLibraryApi(page);
    await triggerWorkbenchLibrary(page);
    const pending = page.getByTestId('workbench-library-pending');
    await expect(pending.getByText('Загружаю библиотеку…', { exact: true })).toBeVisible();
    await expect(pending.getByRole('status')).not.toContainText('%');
    await expect(pending.locator('.chakra-spinner')).toHaveCSS('animation-name', 'none');
    await expect.poll(() => chunks).toBe(1);
    await pending.getByRole('button', { name: 'Закрыть библиотеку', exact: true }).click();
    await expect(pending).toHaveCount(0);
    release();
    await openWorkbenchLibrary(page);
    await page.screenshot({ path: info.outputPath('cold-library-recovered.png'), animations: 'disabled' });
    await expectPassive(page, state);
  } finally { release(); }
});

test('Библиотека переключает серверные страницы, не накапливая файлы', async ({ page }) => {
  const state = await installLibraryApi(page);
  state.items = Array.from({ length: 23 }, (_, n) => ({ file_id: `file-${n}`, name: `file-${n}.txt`, availability: 'ready' }));
  const library = await openWorkbenchLibrary(page);
  await expect(library.getByTestId('work-library-file')).toHaveCount(10);
  const more = library.getByRole('button', { name: 'Следующая страница', exact: true });
  await more.focus(); await more.press('Enter');
  await expect(library.getByRole('link', { name: 'Скачать file-10.txt', exact: true })).toBeVisible();
  await expect(library.getByText('file-0.txt', { exact: true })).toHaveCount(0);
  await more.focus(); await more.press('Space');
  await expect(library.getByTestId('work-library-file')).toHaveCount(3);
  await expect(more).toBeDisabled();
  await library.getByRole('button', { name: 'Предыдущая страница', exact: true }).click();
  await expect(library.getByText('file-10.txt', { exact: true })).toBeVisible();
  expect(state.pages.map(params => params.offset)).toEqual([0, 10, 20, 10]);
  expect(state.pages.every(params => params.limit === 10)).toBe(true);
  await expectPassive(page, state);
});

test('Library failed page retains files and keyboard retry without disclosing transport bodies', async ({ page }) => {
  const state = await installLibraryApi(page);
  let attempts = 0;
  state.readPage = async ({ offset }) => {
    if (offset === 0) return { json: { state: 'ready', items: state.items, next_offset: 10 } };
    expect(offset).toBe(10); attempts += 1;
    return attempts <= 3 ? { status: 503, json: { detail: 'private-library-error-marker' } }
      : { json: { state: 'ready', items: [{ file_id: 'second', name: 'second.txt', availability: 'ready' }], next_cursor: null, next_offset: null } };
  };
  const library = await openWorkbenchLibrary(page);
  await expect(library.getByText('brief.txt', { exact: true })).toBeVisible();
  await library.getByRole('button', { name: 'Следующая страница', exact: true }).click();
  await expect(library.getByRole('status').filter({ hasText: 'Не удалось загрузить страницу.' })).toBeVisible();
  await expect(library.getByRole('link', { name: 'Скачать brief.txt', exact: true })).toBeVisible();
  await expect(page.getByText('private-library-error-marker')).toHaveCount(0);
  const retry = library.getByRole('button', { name: 'Повторить загрузку файлов', exact: true });
  await retry.focus(); await retry.press('Enter');
  await expect(library.getByRole('link', { name: 'Скачать second.txt', exact: true })).toBeVisible();
  await expect(library.getByRole('link', { name: 'Скачать brief.txt', exact: true })).toHaveCount(0);
  await expect(retry).toHaveCount(0);
  expect(attempts).toBe(4);
  await page.addScriptTag({ content: axe.source });
  expect(await page.evaluate(async () => (await window.axe.run()).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
  await expectPassive(page, state);
});

for (const width of [393, 1440]) test(`Поиск по всей библиотеке и очистка запроса ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  const state = await installLibraryApi(page);
  state.items = Array.from({ length: 23 }, (_, n) => ({ file_id: `file-${n}`, name: n === 22 ? 'Годовой отчёт.pdf' : `Материалы-${n}.txt` }));
  const library = await openWorkbenchLibrary(page);
  await expect(library.getByTestId('work-library-file')).toHaveCount(10);
  await library.getByRole('button', { name: 'Следующая страница', exact: true }).click();
  await expect(library.getByText('Материалы-10.txt', { exact: true })).toBeVisible();
  const search = library.getByRole('textbox', { name: 'Поиск по библиотеке', exact: true });
  await search.fill('ОТЧЁТ');
  await expect(library.getByText('Годовой отчёт.pdf', { exact: true })).toBeVisible();
  await expect(library.getByTestId('work-library-file')).toHaveCount(1);
  expect(state.pages.at(-1)).toEqual({ offset: 0, limit: 10, q: 'ОТЧЁТ' });
  await search.fill('не существует');
  await expect(library.getByText('Файлы с таким именем не найдены.', { exact: true })).toBeVisible();
  await library.getByRole('button', { name: 'Очистить поиск по библиотеке', exact: true }).click();
  await expect(search).toHaveValue('');
  await expect(search).toBeFocused();
  await expect(library.getByTestId('work-library-file')).toHaveCount(10);
  await page.screenshot({ path: info.outputPath(`library-search-${width}.png`) });
  await expectPassive(page, state);
});

test('Library native download returns the owned bytes without creating a workspace or copying', async ({ page }) => {
  const state = await installLibraryApi(page);
  const body = 'owned synthetic Library content';
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/plain',
      'Content-Disposition': 'attachment; filename="brief.txt"', Connection: 'close' });
    response.end(body);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const artifact = `http://127.0.0.1:${server.address().port}/fixture`;
  await page.context().route('**/api/service/files/v1/file-opaque-1/download', route => route.continue({ url: artifact }));
  const downloads = [];
  const receive = download => downloads.push(download);
  const popup = opened => opened.on('download', receive);
  page.on('download', receive); page.context().on('page', popup);
  try {
    const library = await openWorkbenchLibrary(page);
    const link = library.getByRole('link', { name: 'Скачать brief.txt', exact: true });
    await link.focus(); await link.press('Enter');
    await expect.poll(() => downloads.length).toBe(1);
    const [download] = downloads;
    try {
      expect(await download.failure()).toBeNull();
      expect(download.suggestedFilename()).toBe('brief.txt');
      const chunks = [];
      for await (const chunk of await download.createReadStream()) chunks.push(chunk);
      expect(Buffer.concat(chunks).toString()).toBe(body);
    } finally { await download.delete(); }
    await expectPassive(page, state);
  } finally {
    page.off('download', receive); page.context().off('page', popup);
    await new Promise(resolve => server.close(resolve));
  }
});
