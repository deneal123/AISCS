const { test, expect } = require('@playwright/test');
const axe = require('axe-core');
const { installLibraryApi } = require('./helpers/libraryApi');

test.use({ serviceWorkers: 'block' });

async function openMemory(page, facts = [], dashboard = {}) {
  await installLibraryApi(page);
  const state = { facts, failSave: false, writes: [] };
  await page.route('**/api/memory/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === 'POST') {
      state.writes.push(request.postDataJSON());
      if (state.failSave) { await route.fulfill({ status: 409, json: { code: 'conflict' } }); return; }
      state.facts.push({ id: `fact-${state.writes.length}`, ...request.postDataJSON() });
      await route.fulfill({ json: { ok: true } }); return;
    }
    const query = url.searchParams.get('q');
    await route.fulfill({ json: url.pathname.endsWith('/dashboard') ? dashboard : {
      facts: query ? state.facts.filter(fact => fact.fact_value.includes(query)) : state.facts,
    } });
  });
  const action = page.getByRole('button', { name: 'Память и контекст', exact: true });
  if (!await action.isVisible()) {
    const menu = page.getByRole('button', { name: 'Меню', exact: true });
    if (await menu.isVisible()) await menu.click();
    else await page.getByRole('button', { name: 'Переключить сайдбар', exact: true }).click();
  }
  await action.click();
  const panel = page.getByTestId('memory-drawer');
  await expect(panel).toBeVisible();
  await expect.poll(() => panel.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return bounds.left >= -1 && bounds.right <= innerWidth + 1;
  })).toBe(true);
  return { panel, state };
}

for (const width of [320, 393, 1440]) {
  test(`память: компактная пустая панель, форма и сохранение ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 720 });
    const { panel, state } = await openMemory(page);
    await expect(panel.getByText('Пока нет фактов', { exact: true })).toBeVisible();
    const add = panel.getByRole('button', { name: 'Добавить факт', exact: true });
    await expect(add).toHaveCount(1);
    await expect(panel.getByRole('textbox', { name: 'Добавить факт вручную', exact: true })).toHaveCount(0);
    const empty = panel.getByText('Пока нет фактов', { exact: true });
    expect((await empty.boundingBox()).y).toBeLessThan(350);
    await page.screenshot({ path: info.outputPath(`memory-empty-${width}.png`), animations: 'disabled' });
    await add.click();
    const input = panel.getByRole('textbox', { name: 'Добавить факт вручную', exact: true });
    await expect(input).toBeFocused();
    await input.fill('Предпочитаю короткие ответы\nПримеры — на русском');
    await panel.getByRole('button', { name: 'Сохранить факт', exact: true }).click();
    await expect(input).toHaveCount(0);
    await expect(add).toBeFocused();
    await expect(panel.getByText('Предпочитаю короткие ответы Примеры — на русском', { exact: true })).toBeVisible();
    expect(state.writes).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const remove = panel.getByRole('button', { name: 'Удалить факт', exact: true });
    await expect(remove).toBeVisible();
    const bounds = await remove.boundingBox();
    expect(bounds.width).toBe(44); expect(bounds.height).toBe(44);
    await page.addScriptTag({ content: axe.source });
    const violations = await page.evaluate(async () => (await window.axe.run(document.querySelector('[data-testid="memory-drawer"]')))
      .violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id));
    expect(violations).toEqual([]);
    await page.screenshot({ path: info.outputPath(`memory-fact-${width}.png`) });
  });
}

test('память: ошибка не теряет черновик, поиск очищается с возвратом фокуса', async ({ page }, info) => {
  await page.setViewportSize({ width: 393, height: 720 });
  const { panel, state } = await openMemory(page, [{
    id: 'existing', fact_type: 'preference', fact_key: 'Ответы', fact_value: 'Кратко и по делу',
  }]);
  await expect(panel.getByText('Кратко и по делу', { exact: true })).toBeVisible();
  const search = panel.getByRole('textbox', { name: 'Поиск по памяти', exact: true });
  await search.fill('нет совпадений');
  await expect(panel.getByText('Ничего не найдено', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Очистить поиск', exact: true }).click();
  await expect(search).toBeFocused();
  await expect(panel.getByText('Кратко и по делу', { exact: true })).toBeVisible();
  state.failSave = true;
  await panel.getByRole('button', { name: 'Добавить факт', exact: true }).click();
  const input = panel.getByRole('textbox', { name: 'Добавить факт вручную', exact: true });
  await input.fill('Несохранённый черновик');
  await panel.getByRole('button', { name: 'Сохранить факт', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('Текст оставлен');
  await expect(input).toHaveValue('Несохранённый черновик');
  await page.screenshot({ path: info.outputPath('memory-save-error.png') });
});

for (const width of [320, 1440]) test(`MemOS: настоящее скрытие и ограниченное чтение записи ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 800 });
  const raw = `Резюме предыдущего диалога: ${JSON.stringify({
    role: 'user', content: 'Важные сведения о проекте. '.repeat(120), ts: 123,
  })}, ${JSON.stringify({ role: 'assistant', content: 'Резюме без потери смысла.' })}`;
  const { panel, state } = await openMemory(page, [], { text_mem: [{ memories: ['Короткая запись', raw] }] });
  const hide = panel.getByRole('button', { name: 'Скрыть семантическую память', exact: true });
  await expect(hide).toBeVisible();
  await expect(panel.getByText('Короткая запись', { exact: true })).toBeVisible();
  const read = panel.getByRole('button', { name: 'Читать запись', exact: true });
  await read.click();
  const content = panel.getByRole('region', { name: 'Полный текст записи 1', exact: true });
  await expect(content).toContainText('Вы: Важные сведения');
  await expect(content).not.toContainText('"role"');
  expect((await content.boundingBox()).height).toBeLessThanOrEqual(261);
  expect(await content.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await panel.getByRole('button', { name: 'Свернуть запись', exact: true }).click();
  await hide.focus(); await hide.press('Enter');
  await expect(panel.getByText('Короткая запись', { exact: true })).toHaveCount(0);
  const expand = panel.getByRole('button', { name: 'Раскрыть семантическую память', exact: true });
  await expect(expand).toHaveAttribute('aria-expanded', 'false');
  await expand.press('Space');
  await expect(panel.getByText('Короткая запись', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Читать запись', exact: true }).scrollIntoViewIfNeeded();
  expect(state.writes).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => (await window.axe.run(document.querySelector('[data-testid="memory-drawer"]')))
    .violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id));
  expect(violations).toEqual([]);
  await page.screenshot({ path: info.outputPath(`memos-previews-${width}.png`), animations: 'disabled' });
});
