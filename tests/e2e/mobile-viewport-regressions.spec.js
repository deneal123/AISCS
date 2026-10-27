const { test, expect } = require('@playwright/test');
const { fixture, THREAD, PROJECT } = require('./helpers/pdfApi');
const { installVisualViewport } = require('./helpers/visualViewport');
const { questionFixture, parkQuestion } = require('./helpers/humanQuestions');

test.use({ serviceWorkers: 'block' });

async function expectAccessibleInput(input) {
  await expect(input).toBeInViewport({ ratio: 1 });
  expect(await input.evaluate(node => {
    const r = node.getBoundingClientRect();
    return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === node;
  })).toBe(true);
}

test('общая оболочка следует видимой области без второго скролла страницы', async ({ page }, info) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await installVisualViewport(page);
  await fixture(page, { initialSurface: 'chat' });
  const root = page.locator('#main').locator('..');
  const composer = page.locator('[data-composer-container]');
  for (const [height, top] of [[600, 0], [390, 45], [600, 0], [800, 0]]) {
    await page.evaluate(([height, top]) => window.setTestVisualViewport(height, top), [height, top]);
    await expect.poll(async () => (await root.boundingBox()).height).toBe(height);
    const bounds = await root.boundingBox();
    expect(bounds.y).toBe(top);
    const input = await composer.boundingBox();
    expect(input.y + input.height).toBeLessThanOrEqual(height + top + 1);
    expect(input.y + input.height).toBeGreaterThanOrEqual(height + top - 1);
    await page.screenshot({ path: info.outputPath(`chat-${height}-${top}.png`), animations: 'disabled' });
    await page.evaluate(() => window.scrollTo(0, 100));
    const brand = await page.locator('header').first().boundingBox();
    const thread = await page.locator('header').nth(1).boundingBox();
    expect(thread.y).toBeGreaterThanOrEqual(brand.y + brand.height - 1);
  }
});

test('мобильный PDF не накладывает проверки и превью на поле при открытии клавиатуры', async ({ page }, info) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await installVisualViewport(page);
  const state = await fixture(page);
  await page.getByRole('group', { name: 'Области PDF-студии', exact: true })
    .getByRole('button', { name: 'Превью', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.focus();
  for (const [height, top] of [[600, 0], [390, 45], [600, 0]]) {
    await page.evaluate(([height, top]) => window.setTestVisualViewport(height, top), [height, top]);
    await expect.poll(async () => (await page.locator('[data-product-viewport]').boundingBox()).height).toBe(height);
    const dock = await page.getByTestId('pdf-assistant-dock').boundingBox();
    const preview = await page.getByTestId('pdf-preview-pane').boundingBox();
    await page.screenshot({ path: info.outputPath(`pdf-${height}-${top}.png`), animations: 'disabled' });
    expect(preview.height).toBeGreaterThanOrEqual(44);
    expect(preview.y + preview.height).toBeLessThanOrEqual(dock.y + 1);
    await expect(page.getByTestId('pdf-preview-pane')).toHaveCSS('overflow-y', 'auto');
    expect(dock.y + dock.height).toBeLessThanOrEqual(top + height + 1);
    // Полный checks может выходить за bounds своего скроллера, но не рисоваться
    // поверх соседнего dock. Проверяем фактическое попадание в поле ввода.
    await expectAccessibleInput(input);
    const mode = page.getByRole('button', { name: 'Режим: Авто', exact: true });
    await mode.focus();
    await expect(mode).toBeInViewport({ ratio: 1 });
    await input.focus();
    await expect(input).toBeInViewport({ ratio: 1 });
    const toggle = page.getByTestId('pdf-checks-bar').getByRole('button', { name: 'Проверки', exact: true });
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expectAccessibleInput(input);
    await toggle.click();
  }
  expect(state.writes).toHaveLength(0);
  expect(state.builds).toHaveLength(0);
  expect(state.requests).toHaveLength(0);
});

test('ограничение рабочего viewport не закрепляет обычную страницу аккаунта', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await installVisualViewport(page);
  await fixture(page, { initialSurface: 'chat' });
  await page.goto('/billing', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#main')).toBeVisible();
  await page.evaluate(() => window.setTestVisualViewport(600, 0));
  await expect(page.locator('[data-product-viewport]')).toHaveCount(0);
  const root = page.locator('#main').locator('..');
  await expect(root).toHaveCSS('position', 'relative');
  await expect(root).toHaveCSS('min-height', '800px');
});

for (const stage of ['trace', 'question', 'cost']) test(`PDF ${stage}: resize/pan сохраняет доступ к этапам и безопасным действиям`, async ({ page }, info) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await installVisualViewport(page);
  const state = await fixture(page);
  let surface;
  let action;
  if (stage === 'trace') {
    await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Проверь структуру');
    await page.getByRole('button', { name: 'Отправить', exact: true }).click();
    await expect.poll(() => state.requests.length).toBe(1);
    state.socket.send(JSON.stringify({ type: 'job_created', job_id: 'pdf-job-1', celery_task_id: 'pdf-task-1', document_project: PROJECT }));
    for (let index = 0; index < 16; index += 1) state.socket.send(JSON.stringify({
      type: 'status_update', job_id: 'pdf-job-1', metadata: {
        kind: 'document_status', document_status: { stage: index % 2 ? 'outline' : 'section_authoring', status: 'running' },
      },
    }));
    surface = page.getByRole('region', { name: 'Этапы выполнения', exact: true });
    action = page.getByRole('button', { name: 'Остановить генерацию', exact: true });
  } else {
    const question = await questionFixture(page, { threadId: THREAD, projectId: PROJECT, surface: 'pdf' });
    if (stage === 'cost') question.cost = { ...question.cost, state: 'pending', estimated_credits: 5000 };
    surface = await parkQuestion(page, () => state.socket, question.snapshot, state.requests);
    action = surface.getByRole('button', { name: 'Не продолжать', exact: true });
    if (stage === 'cost') {
      await surface.getByRole('button', { name: 'Минимальная структура', exact: true }).click();
      await surface.getByRole('button', { name: 'Продолжить', exact: true }).click();
      surface = page.getByRole('region', { name: 'Подтверждение стоимости', exact: true });
      action = surface.getByRole('button', { name: 'Не запускать', exact: true });
    }
  }
  for (const [height, top] of [[600, 0], [390, 45], [600, 0]]) {
    await page.evaluate(([height, top]) => window.setTestVisualViewport(height, top), [height, top]);
    await expect.poll(async () => (await page.locator('[data-product-viewport]').boundingBox()).height).toBe(height);
    await expect(surface).toBeVisible();
    const bounds = await action.boundingBox();
    expect(bounds.y).toBeGreaterThanOrEqual(top);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(top + height);
    await expect(action).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: info.outputPath(`${stage}-${height}-${top}.png`), animations: 'disabled' });
  }
  expect(state.requests).toHaveLength(1);
  expect(state.writes).toHaveLength(0);
  expect(state.builds).toHaveLength(0);
});
