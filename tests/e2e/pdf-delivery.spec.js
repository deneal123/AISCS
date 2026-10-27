const { test, expect } = require('@playwright/test');
const { fixture, THREAD } = require('./helpers/pdfApi');

test.use({ serviceWorkers: 'block' });

async function showChecks(page) {
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Превью', exact: true }).click();
  const checks = page.getByTestId('pdf-checks-bar');
  const toggle = checks.getByRole('button', { name: 'Проверки', exact: true });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  return checks;
}

async function enterFinal(page, options = {}) {
  const state = await fixture(page, { initialSurface: 'chat' });
  state.build = { build_id: 'delivery-build', state: 'ready', final: true,
    artifacts: [{ artifact_id: 'delivery-pdf', role: 'pdf' }] };
  const counts = { publish: 0, status: 0 };
  let publication = null;
  let failRead = false;
  await page.route('**/documents/builds/delivery-build/artifacts/delivery-pdf/publish', async route => {
    counts.publish += 1;
    publication = 'pending_delivery';
    failRead = !options.deadline;
    await route.fulfill({ status: 202, json: { publication_state: publication } });
  });
  await page.route('**/documents/builds/delivery-build', async route => {
    counts.status += 1;
    if (failRead) {
      failRead = false;
      await route.fulfill({ status: 503, json: { detail: 'private-delivery-body' } }); return;
    }
    if (options.deadline && publication && counts.status === 2) {
      await options.heldRead;
      try { await route.fulfill({ json: { ...state.build, publication_state: 'delivered' } }); } catch { /* aborted read, not cancelled publication */ }
      return;
    }
    await route.fulfill({ json: { ...state.build, publication_state: publication ? 'delivered' : null } });
  });
  await page.getByRole('button', { name: 'PDF', exact: true }).click();
  const title = page.getByRole('textbox', { name: 'Название документа', exact: true });
  await title.fill('Локальная правка не входит в опубликованный PDF');
  const checks = await showChecks(page);
  const publish = checks.getByRole('button', { name: 'Сохранить в Библиотеку', exact: true });
  await expect(publish).toBeEnabled();
  return { state, counts, title, publish, checks };
}

test('publication read recovery preserves the local draft and never resubmits delivery', async ({ page }, info) => {
  const { state, counts, title, publish, checks } = await enterFinal(page);
  await publish.click();
  const recovery = page.locator('[aria-label="Состояние сохранения документа"]:visible');
  await expect(recovery).toContainText('Оно могло завершиться');
  await expect(publish).toBeDisabled();
  expect(counts.publish).toBe(1);
  await expect(page.getByText('private-delivery-body', { exact: true })).toHaveCount(0);
  const retry = recovery.getByRole('button', { name: 'Проверить сохранение', exact: true });
  await retry.focus(); await retry.press('Enter');
  await expect(checks.locator('[aria-label="Этапы подготовки документа"]:visible')).toContainText('Сохранён в Библиотеке');
  await expect(recovery).toHaveCount(0);
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Редактор', exact: true }).click();
  await expect(title).toHaveValue('Локальная правка не входит в опубликованный PDF');
  expect(counts.publish).toBe(1); expect(state.writes).toHaveLength(0); expect(state.requests).toHaveLength(0);
  await page.screenshot({ path: info.outputPath('publication-recovery-current.png') });
});

test('publication observation deadline releases UI without cancelling or repeating delivery', async ({ page }) => {
  let release;
  const heldRead = new Promise(resolve => { release = resolve; });
  try {
    const { state, counts, title, publish, checks } = await enterFinal(page, { deadline: true, heldRead });
    await page.clock.install();
    await publish.click();
    await expect.poll(() => counts.status).toBe(2);
    const recovery = page.locator('[aria-label="Состояние сохранения документа"]:visible');
    await expect(recovery).toContainText('Проверяю сохранение');
    await page.clock.fastForward(300_000);
    await expect(recovery).toContainText('Оно могло завершиться');
    await expect(publish).toBeDisabled();
    const retry = recovery.getByRole('button', { name: 'Проверить сохранение', exact: true });
    await expect(retry).toBeEnabled();
    await retry.focus(); await retry.press('Enter');
    await expect(checks.locator('[aria-label="Этапы подготовки документа"]:visible')).toContainText('Сохранён в Библиотеке');
    expect(counts.status).toBe(3); expect(counts.publish).toBe(1);
    if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Редактор', exact: true }).click();
    await expect(title).toHaveValue('Локальная правка не входит в опубликованный PDF');
    expect(state.writes).toHaveLength(0); expect(state.requests).toHaveLength(0);
  } finally { release(); }
});

test('PDF preview read failure remains inline and explicit keyboard retry opens one owned viewer', async ({ page }) => {
  const state = await fixture(page, { initialSurface: 'chat' });
  state.build = { build_id: 'delivery-build', state: 'preview_ready', artifacts: [{ artifact_id: 'delivery-pdf', role: 'pdf' }] };
  let reads = 0;
  await page.route('**/documents/builds/delivery-build/artifacts/delivery-pdf', async route => {
    reads += 1;
    if (reads === 1) await route.fulfill({ status: 503, json: { detail: 'private-preview-body' } });
    else await route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' });
  });
  await page.getByRole('button', { name: 'PDF', exact: true }).click();
  if (page.viewportSize().width < 1100) await page.getByRole('button', { name: 'Превью', exact: true }).click();
  const preview = page.getByRole('button', { name: 'Открыть PDF', exact: true });
  await preview.focus(); await preview.press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: 'Не удалось открыть превью.' })).toBeVisible();
  await expect(page.getByText('private-preview-body', { exact: true })).toHaveCount(0);
  await preview.focus(); await preview.press('Enter');
  await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveCount(1);
  await expect(page.locator('iframe[title="Предпросмотр PDF"]')).toHaveAttribute('src', /^blob:/);
  expect(reads).toBe(2); expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
});

test('Library vendor kit is installed only through the guarded formatting action', async ({ page }) => {
  const state = await fixture(page, { initialSurface: 'chat' });
  state.library = [{ file_id: 'vendor-fixture', name: 'journal-kit.zip', file_type: 'application/zip', availability: 'ready' }];
  const mutations = [];
  await page.route('**/documents/vendor/vendor-fixture', async route => {
    mutations.push(route.request().postDataJSON());
    state.revision = 'revision-2';
    const overlay = { package_id: 'journal-kit', version: '1.0', license: 'LPPL-1.3c', file_count: 3, trusted: false, export_allowed: false };
    state.vendorOverlays = [overlay];
    await route.fulfill({ json: { outcome: 'imported', revision: state.revision, overlay } });
  });
  await page.getByRole('button', { name: 'PDF', exact: true }).click();
  await page.getByRole('button', { name: 'Оформление', exact: true }).click();
  const panel = page.getByRole('dialog');
  await expect(panel.getByText('Шаблон издателя', { exact: true })).toBeVisible();
  expect(mutations).toHaveLength(0);
  await expect(panel.getByRole('button', { name: 'Добавить в проект', exact: true })).toBeHidden();
  await panel.getByText('Шаблон издателя', { exact: true }).click();
  expect(mutations).toHaveLength(0);
  await panel.getByRole('button', { name: 'Добавить в проект', exact: true }).click();
  await expect(panel.getByText('journal-kit', { exact: true })).toBeVisible();
  expect(mutations).toEqual([{ path: 'documents/paper', expected_revision: 'revision-1', fence: 3 }]);
  expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
});
