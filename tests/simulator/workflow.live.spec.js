const { test, expect } = require('@playwright/test');
const fs = require('fs');
const { createHash } = require('crypto');

test.skip(!process.env.SIMULATION_E2E_STATE || !process.env.SIMULATION_E2E_RUN,
  'Requires an authenticated owner and its completed record');
const sceneName = 'Трёхмерная сцена мухи и локальной модели';
async function open(page) {
  await page.goto('/simulator?run=' + process.env.SIMULATION_E2E_RUN);
  await expect(page.getByLabel(sceneName, { exact: true })).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
}

test('placement navigation discards uncommitted coordinates and fullscreen preserves playback controls', async ({ page }, info) => {
  await open(page);
  const electrode = page.getByRole('button', { name: 'Электроды', exact: true });
  await electrode.click();
  const y = page.getByLabel('Y, мкм', { exact: true });
  const original = await y.inputValue();
  await y.fill(String(Number(original) + 80));
  await page.getByRole('button', { name: 'Параметры модели', exact: true }).click();
  await electrode.click();
  await expect(y).toHaveValue(original);
  await y.fill(String(Number(original) + 80));
  await electrode.click();
  await page.keyboard.press('Escape');
  await electrode.click();
  await expect(y).toHaveValue(original);
  const applied = String(Number(original) + 80);
  await y.fill(applied);
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await page.getByRole('button', { name: 'Полноэкранный показ', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true);
  await expect(page.getByRole('complementary', { name: 'Опыты', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Воспроизвести запись', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Запустить', exact: true })).toBeVisible();
  await expect(page.getByText('Черновик параметров · запись сохранённого опыта', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('presentation-mode.png') });
  await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(false);
  await expect(page.getByRole('complementary', { name: 'Опыты', exact: true })).toBeVisible();
  await electrode.click();
  await expect(y).toHaveValue(applied);
  await y.fill(String(Number(applied) + 20));
  await page.getByRole('button', { name: 'Файлы', exact: true }).click();
  await page.getByRole('button', { name: 'Сцена', exact: true }).click();
  await electrode.click();
  await expect(y).toHaveValue(applied);
});

test('real WebGL loss retains recording, artifact retry and independently checked downloads', async ({ page }, info) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await open(page);
  const scene = page.getByLabel(sceneName, { exact: true });
  expect(await scene.evaluate(canvas => {
    const extension = canvas.getContext('webgl2').getExtension('WEBGL_lose_context');
    if (!extension) return false;
    extension.loseContext(); return true;
  })).toBe(true);
  await expect(page.getByRole('alert').filter({ hasText: 'Графический контекст потерян' })).toBeVisible();
  let inject = true;
  await page.route(/\/api\/simulations\/v1\/runs\/[^/]+\/artifacts$/, async route => {
    if (inject) { await route.fulfill({ status: 503, json: { detail: 'temporary artifact read failure' } }); }
    else await route.continue();
  });
  await page.getByRole('button', { name: 'Файлы', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Повторить загрузку файлов', exact: true })).toBeVisible();
  inject = false;
  await page.getByRole('button', { name: 'Повторить загрузку файлов', exact: true }).click();
  const files = page.getByRole('region', { name: 'Файлы выбранного опыта', exact: true });
  await expect(files.getByRole('button', { name: /^Скачать / })).toHaveCount(10);
  const runId = process.env.SIMULATION_E2E_RUN;
  const manifestResponse = await page.request.get('/api/simulations/v1/runs/' + runId + '/manifest');
  expect(manifestResponse.ok()).toBe(true);
  const manifest = await manifestResponse.json();
  const manifestDownload = page.waitForEvent('download');
  await files.getByRole('button', { name: 'Манифест', exact: true }).click();
  const downloadedManifest = JSON.parse(fs.readFileSync(await (await manifestDownload).path(), 'utf8'));
  expect(downloadedManifest).toEqual(manifest);
  const download = page.waitForEvent('download');
  await files.getByRole('button', { name: 'Скачать signals.csv', exact: true }).click();
  const signal = fs.readFileSync(await (await download).path());
  expect(createHash('sha256').update(signal).digest('hex')).toBe(manifest.files.find(file => file.name === 'signals.csv').sha256);
  await page.getByRole('button', { name: 'Запись', exact: true }).click();
  await expect(page.getByText('Матрица ошибок: строки — истинный класс, столбцы — предсказанный', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Сцена', exact: true }).click();
  await expect(scene).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(page.getByRole('alert').filter({ hasText: 'Графический контекст потерян' })).toHaveCount(0);
  const oldCanvas = await scene.elementHandle();
  await scene.evaluate(canvas => canvas.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext());
  await page.getByRole('button', { name: 'Восстановить 3D-сцену', exact: true }).click();
  await expect.poll(() => oldCanvas.evaluate(canvas => canvas.isConnected)).toBe(false);
  await expect(scene).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(page.getByRole('alert').filter({ hasText: 'Графический контекст потерян' })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('graphics-recovered.png') });
  expect(errors).toEqual([]);
});

test('older experiments remain reachable through real server pages without submitting work', async ({ page }) => {
  const pages = []; let calculations = 0;
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/api/simulations/v1/runs')) calculations += 1; });
  // Exercise the actual owner-filtered backend with smaller pages; no synthetic records.
  await page.route(/\/api\/simulations\/v1\/runs\?/, async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('limit', '3'); pages.push(Number(url.searchParams.get('offset')));
    await route.continue({ url: url.toString() });
  });
  await open(page);
  const entries = page.locator('[data-run-id]');
  await expect(entries).toHaveCount(3);
  const firstIds = await entries.evaluateAll(nodes => nodes.map(node => node.dataset.runId));
  await page.getByRole('button', { name: 'Ещё опыты', exact: true }).click();
  await expect(entries).toHaveCount(6);
  const ids = await entries.evaluateAll(nodes => nodes.map(node => node.dataset.runId));
  expect(ids.slice(0, 3)).toEqual(firstIds); expect(new Set(ids).size).toBe(6);
  await entries.nth(5).click();
  await expect(page).toHaveURL(new RegExp('run=' + ids[5]));
  expect(pages).toEqual([0, 3]); expect(calculations).toBe(0);
});
