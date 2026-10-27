const { test, expect } = require('@playwright/test');
const axe = require('axe-core');
const { installVisualViewport } = require('./helpers/visualViewport');
const { scrollSurface } = require('./helpers/scrollSurface');
const { openWorkbenchLibrary, closeWorkbenchLibrary } = require('./helpers/workbenchLibrary');
const { revealWorkspaceFile } = require('./helpers/workspaceTree');
const { questionFixture, parkQuestion, exerciseUnknownCostStop } = require('./helpers/humanQuestions');

test.use({ serviceWorkers: 'block' });
const { fixture, THREAD, PROJECT, PROPOSAL } = require('./helpers/pdfApi');

for (const width of [1440, 393]) test(`PDF task result blocker survives transport completion ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  const state = await fixture(page);
  await startDocumentRun(page, state);
  state.socket.send(JSON.stringify({
    type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Подтверждённая часть результата сохранена.',
    metadata: {
      execution_status: 'completed', document_project: PROJECT,
      task_result: {
        schema_version: 2, status: 'blocked', verified: false, blocker: 'cost_unknown',
        confirmed: [], unchecked: ['slides'], references: [], rounds: 2, repair_cycles: 0,
      },
    },
  }));
  const activity = page.getByRole('region', { name: 'Выполнение запроса документа', exact: true });
  await expect(activity.getByRole('status')).toContainText('Задача заблокирована');
  await expect(activity.getByRole('status')).toContainText('Расход ещё не подтверждён');
  await expect(activity.getByRole('status')).not.toContainText('Запрос завершён');
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
  await expect(activity.getByRole('button', { name: 'Остановить генерацию' })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('task-result-blocked.png'), animations: 'disabled' });
  await activity.getByRole('button', { name: 'Этапы', exact: true }).click();
  await expect(activity.getByText('Задача заблокирована', { exact: true })).toBeVisible();
  const bounds = await activity.boundingBox();
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(851);
  expect(bounds.height).toBeLessThanOrEqual(361);
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => (await window.axe.run(
    document.querySelector('[data-testid="document-assistant-activity"]'),
  )).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id));
  expect(violations).toEqual([]);
  expect(state.requests).toHaveLength(1); expect(state.writes).toHaveLength(0);
  expect(state.builds).toHaveLength(0);
});
test('PDF splitter applies touch-action as CSS without React DOM warnings', async ({ page }) => {
  const warnings = [];
  page.on('console', message => {
    if (message.type() === 'error' && message.text().includes('touchAction')) warnings.push(message.text());
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixture(page);
  const splitter = page.getByRole('separator', { name: 'Ширина редактора и превью', exact: true });
  await expect(splitter).toBeVisible();
  await expect(splitter).toHaveCSS('touch-action', 'none');
  expect(await splitter.getAttribute('touchaction')).toBeNull();
  const before = Number(await splitter.getAttribute('aria-valuenow'));
  await splitter.focus();
  await page.keyboard.press('ArrowRight');
  await expect(splitter).toHaveAttribute('aria-valuenow', String(before + 2));
  expect(warnings).toEqual([]);
});

for (const width of [1440, 393]) test(`PDF unknown cost Stop ${width}px checks the same child without another run`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: width === 393 ? 360 : 700 });
  const state = await fixture(page);
  const question = await questionFixture(page, { threadId: THREAD, projectId: PROJECT, surface: 'pdf' });
  question.cost = { ...question.cost, state: 'pending', estimated_credits: 5000 };
  await parkQuestion(page, () => state.socket, question.snapshot, state.requests);
  await exerciseUnknownCostStop(page, question, state.requests, info);
  expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
});
const { watchComposerGeometry, sampleComposerGeometry } = require('./helpers/composerGeometry');
const { checkComposerInvitation } = require('./helpers/actionHints');

for (const width of [1440, 393]) test(`PDF next-action input invitation survives peer changes ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await fixture(page);
  for (const label of ['PDF', 'Чат', 'PDF']) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await checkComposerInvitation(page);
  }
});

for (const width of [1440, 393]) test(`PDF and Chat composer controls have final geometry from the first visible frame ${width}px`, async ({ page, browserName }) => {
  // Preserve all four24-frame observations when mobile WebKit idle-throttles
  // RAF to1Hz at this wide emulated viewport. Readiness assertions stay unchanged.
  if (browserName === 'webkit' && width === 1440) test.setTimeout(180000);
  await page.setViewportSize({ width, height: 900 });
  await watchComposerGeometry(page);
  await fixture(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Сохранить черновик при переходах');
  for (const label of ['Чат', 'PDF', 'Чат', 'PDF']) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect(input).toBeVisible();
    expect(await sampleComposerGeometry(page)).toEqual({ mismatches: [], transitions: [] });
    await expect(input).toHaveValue('Сохранить черновик при переходах');
  }
});

for (const width of [1440, 393]) test(`PDF human question ${width}px supports free text and cancel without another agent request`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 700 });
  const state = await fixture(page);
  const question = await questionFixture(page, { threadId: THREAD, projectId: PROJECT, surface: 'pdf' });
  const panel = await parkQuestion(page, () => state.socket, question.snapshot, state.requests);
  await panel.getByLabel('Свой ответ или детали').fill('Собственная структура');
  await expect(panel.getByRole('button', { name: 'Продолжить', exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('pdf-human-question.png'), animations: 'disabled' });
  const bounds = await panel.getByRole('button', { name: 'Не продолжать', exact: true }).boundingBox();
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(700);
  await panel.getByRole('button', { name: 'Не продолжать', exact: true }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByText('Вопрос отменён. Агент не продолжал работу.', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeFocused();
  expect(question.answers).toHaveLength(0); expect(question.cancels).toBe(1);
  expect(state.requests).toHaveLength(1); expect(state.writes).toHaveLength(0);
  expect(state.builds).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('PDF human question stays scrollable with stable actions and errors in a short viewport', async ({ page, browserName }, info) => {
  await page.setViewportSize({ width: 393, height: 360 });
  const state = await fixture(page);
  const question = await questionFixture(page, { threadId: THREAD, projectId: PROJECT, surface: 'pdf' });
  question.snapshot.prompt = 'Какую структуру документа нужно использовать в этом проекте? '.repeat(12).trim();
  question.question = { ...question.snapshot };
  const panel = await parkQuestion(page, () => state.socket, question.snapshot, state.requests);
  const body = panel.locator('> div').first();
  const dock = page.getByTestId('pdf-assistant-dock');
  const before = await dock.boundingBox();
  await scrollSurface(page, body, { browserName, isMobile: info.project.use.isMobile });
  await expect.poll(() => body.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
  await panel.getByLabel('Свой ответ или детали').fill('Оставить один слайд');
  question.loseAnswer = true;
  await panel.getByRole('button', { name: 'Продолжить', exact: true }).click();
  const check = panel.getByRole('button', { name: 'Проверить состояние', exact: true });
  await expect(check).toBeVisible();
  const bounds = await check.boundingBox();
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(360);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(393);
  expect(await dock.boundingBox()).toEqual(before);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('pdf-question-short-unknown.png'), animations: 'disabled' });
  expect(question.answers).toHaveLength(1); expect(state.requests).toHaveLength(1);
});

for (const height of [700, 360]) test(`PDF continuation cost ${height}px restores expiry, refreshes explicitly and declines without another request`, async ({ page, browserName }, info) => {
  await page.setViewportSize({ width: 393, height });
  const state = await fixture(page);
  const question = await questionFixture(page, { threadId: THREAD, projectId: PROJECT, surface: 'pdf' });
  question.cost = { ...question.cost, state: 'expired', estimated_credits: 5000 };
  const panel = await parkQuestion(page, () => state.socket, question.snapshot, state.requests);
  await panel.getByRole('button', { name: 'Минимальная структура', exact: true }).click();
  await panel.getByRole('button', { name: 'Продолжить', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Обновить оценку', exact: true })).toBeVisible();
  question.history = [{ sender: 'user', content: 'Подготовь проект и уточни структуру', created_at: new Date().toISOString(), metadata: { document_project: PROJECT } },
    { sender: 'assistant', content: question.snapshot.prompt, created_at: new Date(Date.now() + 1).toISOString(),
      metadata: { document_project: PROJECT, human_question: question.snapshot, execution_status: 'waiting_user' } }];
  await page.reload({ waitUntil: 'domcontentloaded' });
  const consent = page.getByRole('region', { name: 'Подтверждение стоимости', exact: true });
  const refresh = consent.getByRole('button', { name: 'Обновить оценку', exact: true });
  await expect(refresh).toBeVisible();
  expect(question.answers).toHaveLength(1); expect(question.decisions).toHaveLength(0);
  expect(question.taskReads).toBe(0);
  const bounds = await consent.boundingBox();
  const footer = await refresh.boundingBox();
  question.loseDecision = true;
  await refresh.click();
  const check = consent.getByRole('button', { name: 'Проверить состояние', exact: true });
  await expect(check).toBeVisible();
  const explanation = consent.getByText('Ответ сохранён. Состояние продолжения нужно проверить.', { exact: true });
  if (height > 400) await expect(explanation).toBeVisible();
  else await expect(explanation).toBeHidden();
  await expect(consent.getByRole('alert')).toContainText('Результат решения пока неизвестен');
  expect(await consent.boundingBox()).toEqual(bounds); expect(await check.boundingBox()).toEqual(footer);
  await check.click();
  await expect(consent.getByRole('button', { name: 'Подтвердить запуск', exact: true })).toBeVisible();
  const amount = consent.getByRole('heading', { name: 'До 5 000 кредитов', exact: true });
  await expect(amount).toBeInViewport({ ratio: 1 });
  const body = consent.locator('> div').first();
  await expect(consent.getByRole('button', { name: 'Не запускать', exact: true })).toBeFocused();
  const keyboard = await scrollSurface(page, body, { browserName, isMobile: info.project.use.isMobile }, 1000);
  if (keyboard) await page.keyboard.press('Tab');
  await expect(amount).toBeInViewport({ ratio: 1 });
  await expect(consent.getByRole('button', { name: 'Не запускать', exact: true })).toBeFocused();
  expect(question.decisions).toHaveLength(1); expect(question.taskReads).toBe(0);
  const pay = await consent.getByRole('button', { name: 'Подтвердить запуск', exact: true }).boundingBox();
  expect(pay.y + pay.height).toBeLessThanOrEqual(height);
  expect(pay.x + pay.width).toBeLessThanOrEqual(393);
  await page.screenshot({ path: info.outputPath('pdf-continuation-cost.png'), animations: 'disabled' });
  await consent.getByRole('button', { name: 'Не запускать', exact: true }).click();
  await expect(consent).toHaveCount(0);
  await expect(page.getByText('Платное продолжение отменено. Агент не продолжал работу.', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeFocused();
  expect(question.decisions.map(item => item.decision)).toEqual(['refresh', 'decline']);
  expect(question.decisions[1].offer_id).not.toBe(question.decisions[0].offer_id);
  expect(state.requests).toHaveLength(1); expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('inaccessible previous-account thread starts PDF on a fresh owned scope', async ({ page }) => {
  await fixture(page, { deniedThread: true });
  await expect(page).toHaveURL(/\/chat\/[a-f0-9-]{36}\?surface=pdf$/);
  await expect(page.getByTestId('pdf-studio')).toBeVisible();
  await expect(page.getByText('Не удалось загрузить рабочее место PDF. Данные не изменены.', { exact: true })).toHaveCount(0);
});

for (const width of [1440, 393]) {
  test(`new PDF document ${width}px recovers a failed format catalog without writing`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await fixture(page, { profileFailure: true });
    const trigger = page.getByRole('button', { name: 'Новый документ', exact: true });
    await expect(trigger).toBeEnabled(); await trigger.click();
    const dialog = page.getByRole('dialog', { name: 'Новый документ', exact: true });
    if (width === 393) {
      const close = dialog.getByRole('button', { name: 'Закрыть новый документ', exact: true });
      await expect.poll(async () => (await close.boundingBox())?.width || 0).toBeGreaterThanOrEqual(44);
      await expect.poll(async () => (await close.boundingBox())?.height || 0).toBeGreaterThanOrEqual(44);
    }
    await expect(dialog.getByRole('alert')).toContainText('Не удалось загрузить форматы');
    await expect(dialog.getByRole('button', { name: 'Создать документ', exact: true })).toBeDisabled();
    state.profileFailure = false;
    await dialog.getByRole('button', { name: 'Повторить загрузку форматов', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Создать документ', exact: true })).toBeEnabled();
    await expect(dialog.getByText('Документ', { exact: true })).toBeVisible();
    expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0); expect(state.requests).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `.work/pdf-new-document-retry-${width}.png`, animations: 'disabled' });
    await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
    await expect(trigger).toBeFocused();
  });
}

test('mobile regression: PDF modal tracks the keyboard and reserves the home indicator', async ({ page }, info) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await installVisualViewport(page);
  await fixture(page);
  const trigger = page.getByRole('button', { name: 'Новый документ', exact: true });
  await expect(trigger).toBeEnabled(); await trigger.click();
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--app-safe-bottom', '34px');
    window.setTestVisualViewport(360, 30);
  });
  const dialog = page.getByRole('dialog', { name: 'Новый документ', exact: true });
  await expect.poll(() => dialog.evaluate(element => element.getBoundingClientRect().bottom)).toBeLessThanOrEqual(356);
  const footer = dialog.getByRole('button', { name: 'Создать документ', exact: true });
  await expect(footer).toBeVisible();
  // This short form may fit; its body must still own overflow for longer copy.
  await expect(dialog.locator('.chakra-modal__body')).toHaveCSS('overflow-y', 'auto');
  const help = dialog.getByText('Открытый документ сохранится. ИИ и сборка не запускаются.', { exact: true });
  await help.scrollIntoViewIfNeeded();
  const helpBounds = await help.boundingBox();
  const footerBounds = await footer.boundingBox();
  expect(helpBounds.y + helpBounds.height).toBeLessThanOrEqual(footerBounds.y);
  await page.screenshot({ path: info.outputPath('mobile-pdf-keyboard.png') });
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  await expect(trigger).toBeFocused();
});

for (const [width, height] of [[1440, 360], [744, 522], [393, 360]]) test(`new document format menu ${width}px scrolls and selects inside a short modal`, async ({ page, browserName }, info) => {
  await page.setViewportSize({ width, height });
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const formatProfiles = [{ profile_id: 'generic_document', label: 'Документ' },
    ...Array.from({ length: 15 }, (_, index) => ({ profile_id: `format_${index}`, label: `Формат документа ${index + 1}` })),
    { profile_id: 'beamer_presentation', label: 'Презентация PDF 16:9' }];
  const state = await fixture(page, { absent: true, readGates: { prepare: gate }, formatProfiles });
  await expect.poll(() => state.preparations.length).toBe(1);
  state.prepareExpired = true; release();
  const trigger = page.getByRole('button', { name: 'Новый документ', exact: true });
  await expect(trigger).toBeEnabled(); await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Новый документ', exact: true });
  await dialog.getByText('Документ', { exact: true }).click();
  const list = page.getByRole('listbox');
  await expect(list).toBeVisible();
  expect(await list.evaluate(node => Boolean(node.closest('[role="dialog"]')))).toBe(true);
  if (browserName === 'webkit' && info.project.use.isMobile) {
    // Mobile WebKit does not implement Playwright mouse.wheel; use its real
    // listbox keyboard owner, not an injected scrollTop masquerading as touch.
    await dialog.getByRole('combobox', { name: 'Формат нового документа', exact: true }).press('End');
  } else {
    await list.hover(); await page.mouse.wheel(0, 1200);
  }
  await expect.poll(() => list.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
  await page.getByRole('option', { name: 'Презентация PDF 16:9', exact: true }).click();
  await expect(dialog.getByText('Презентация PDF 16:9', { exact: true })).toBeVisible();
  await dialog.getByText('Русский', { exact: true }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(dialog.getByText('English', { exact: true })).toBeVisible();
  const format = dialog.getByRole('combobox', { name: 'Формат нового документа', exact: true });
  await format.focus(); await format.press('ArrowDown');
  await expect(page.getByRole('listbox')).toBeVisible();
  await format.press('Escape');
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await expect(dialog).toBeVisible();
  await expect(format).toBeFocused();
  await format.press('ArrowDown'); await format.press('Home'); await format.press('Enter');
  await expect(dialog.getByText('Документ', { exact: true })).toBeVisible();
  await format.press('ArrowDown'); await format.press('End'); await format.press('Enter');
  await expect(dialog.getByText('Презентация PDF 16:9', { exact: true })).toBeVisible();
  const submit = dialog.getByRole('button', { name: 'Создать документ', exact: true });
  await expect(submit).toBeEnabled();
  const bounds = await submit.boundingBox();
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(state.activations).toBe(0); expect(state.createdProjects || []).toHaveLength(0);
  await page.screenshot({ path: info.outputPath('pdf-new-document-short.png'), animations: 'disabled' });
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  await expect(trigger).toBeFocused();
});

async function reviewFixture(page, { gate } = {}) {
  const blocks = [
    { block_id: 'heading', kind: 'section', title: 'Результаты исследования', level: 1 },
    { block_id: 'intro', kind: 'paragraph', text: 'Проверяемый текст документа. '.repeat(30) },
    { block_id: 'table', kind: 'table', title: 'Результаты', columns: ['Метод', 'Значение'], rows: [['A', '2'], ['B', '']] },
    { block_id: 'image', kind: 'figure', title: 'Схема', asset_path: 'figures/before.png' },
    { block_id: 'citation', kind: 'citation', text: 'Проверенный источник', source_id: 1 },
    { block_id: 'formula', kind: 'equation', text: 'E = mc^2' },
    { block_id: 'closing', kind: 'paragraph', text: 'Этот фрагмент не изменяется.' },
  ];
  const state = await fixture(page, { blocks, readGates: { proposal: gate } });
  state.proposal = { proposal_id: PROPOSAL, path: 'documents/paper', stale: false,
    expected_revision: state.revision, authoring_version: 1, draft_digest: 'a'.repeat(64),
    before: state.draft, draft: { ...state.draft, blocks: blocks.map((block) => {
      if (block.block_id === 'heading') return { ...block, level: 2 };
      if (block.block_id === 'intro') return { ...block, text: 'Предлагаемый текст с уточнениями. '.repeat(40) };
      if (block.block_id === 'table') return { ...block, rows: [['A', '3'], ['B', '']] };
      if (block.block_id === 'image') return { ...block, asset_path: 'figures/after.png' };
      if (block.block_id === 'citation') return { ...block, source_id: 2 };
      if (block.block_id === 'formula') return { ...block, text: 'a^2 + b^2 = c^2' };
      return block;
    }) } };
  await startDocumentRun(page, state);
  state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Правки готовы.',
    metadata: { execution_status: 'completed', document_project: PROJECT, document_proposal: PROPOSAL } }));
  await expect(page.getByRole('button', { name: 'Посмотреть изменения', exact: true })).toBeVisible();
  return state;
}

for (const width of [1440, 657, 393, 320]) {
  test(`provider availability groups navigation and account controls at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 851 });
    const state = await fixture(page, { initialSurface: 'chat' });
    const trigger = page.getByRole('button', { name: 'ИИ доступен', exact: true });
    await expect(trigger).toBeVisible();
    const header = page.locator('header').filter({ has: trigger });
    const nav = header.getByRole('group', { name: 'Разделы треда' });
    const account = header.getByRole('group', { name: 'Баланс и настройки' });
    const navBox = await nav.boundingBox();
    const statusBox = await trigger.boundingBox();
    const accountBox = await account.boundingBox();
    expect(navBox.x + navBox.width).toBeLessThanOrEqual(statusBox.x);
    if (width < 768) expect(accountBox.y + accountBox.height).toBeLessThanOrEqual(navBox.y + 1);
    else expect(statusBox.x + statusBox.width).toBeLessThanOrEqual(accountBox.x);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const before = state.statusReads;
    if (width < 768) await trigger.click(); else await trigger.hover();
    await expect(page.getByText('GigaChat', { exact: true })).toBeVisible();
    await expect(page.getByText('Выключен', { exact: true })).toBeVisible();
    const panel = page.getByText('Доступность ИИ', { exact: true }).locator('..');
    const panelBox = await panel.boundingBox();
    // DOM geometry at fractional device pixels can differ by less than one CSS pixel.
    expect(panelBox.x).toBeGreaterThanOrEqual(-0.5);
    expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(width + 0.5);
    expect(state.statusReads).toBe(before);
    expect(state.requests).toHaveLength(0);
    await page.screenshot({ path: `.work/provider-status-${width}.png`, fullPage: true });
    await page.keyboard.press('Escape');
    await expect(page.getByText('GigaChat', { exact: true })).toBeHidden();
    await page.getByRole('button', { name: 'Настройки чата', exact: true }).focus();
    await trigger.focus();
    if (width < 768) await page.keyboard.press('Enter');
    await expect(page.getByText('GigaChat', { exact: true })).toBeVisible();
    await page.addScriptTag({ content: axe.source });
    const severe = await page.evaluate(async () => (await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
    })).violations.filter((item) => ['serious', 'critical'].includes(item.impact)).map((item) => item.id));
    expect(severe).toEqual([]);
  });
}

for (const width of [1440, 393, 320]) {
  test(`provider availability distinguishes cached history from recovered health at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 320 ? 568 : 851 });
    const state = await fixture(page, { initialSurface: 'chat' });
    const trigger = page.getByTestId('provider-availability');
    await expect(trigger).toHaveAccessibleName('ИИ доступен');
    let statusReads = 0;
    let recover = false;
    await page.route('**/api/chats/providers/status', async (route) => {
      statusReads += 1;
      await route.fulfill(recover
        ? { json: { state: 'degraded', ready: 1, total: 2, providers: [
          { id: 'gigachat', label: 'GigaChat', primary: true, state: 'ready' },
          { id: 'routerai', label: 'RouterAI', state: 'unavailable' },
          { id: 'openai', label: 'OpenAI', state: 'disabled' },
        ] } }
        : { json: { state: 'unknown', ready: 0, total: 0, providers: [] } });
    });
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(trigger).toHaveAccessibleName('Доступность ИИ: нет свежих данных');
    await expect.poll(() => statusReads).toBe(1);
    if (width < 768) await trigger.click(); else await trigger.hover();
    const dialog = page.getByRole(width < 768 ? 'dialog' : 'tooltip', { name: 'Доступность ИИ', exact: true });
    await expect(dialog.getByText('При последней проверке: 2 из 2', { exact: true })).toBeVisible();
    await expect(dialog.getByText('Данные устарели', { exact: true })).toHaveCount(3);
    await expect(dialog.getByText('Доступно провайдеров: 2 из 2', { exact: true })).toHaveCount(0);
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(-0.5);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width + 0.5);
    await page.screenshot({ path: info.outputPath('provider-history.png'), animations: 'disabled' });
    expect(statusReads).toBe(1);
    expect(state.requests).toHaveLength(0);

    recover = true;
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(trigger).toHaveAccessibleName('ИИ доступен частично');
    await expect(dialog.getByText('Доступно провайдеров: 1 из 2', { exact: true })).toBeVisible();
    await expect(dialog.getByText('Выключен', { exact: true })).toBeVisible();
    await expect(dialog.getByText('Данные устарели', { exact: true })).toHaveCount(0);
    expect(statusReads).toBe(2);
    expect(state.requests).toHaveLength(0);
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  });

  test(`PDF citation selection uses registered names and saves only explicitly at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 320 ? 568 : 851 });
    const state = await fixture(page);
    await expect(page.getByRole('textbox', { name: 'Название документа', exact: true })).toHaveValue(state.draft.title);
    expect(state.sourceReads).toBe(0);
    const kind = page.getByRole('combobox', { name: 'Тип нового блока', exact: true });
    await kind.fill('Цитирование'); await kind.press('ArrowDown'); await kind.press('Enter');
    const source = page.getByRole('combobox', { name: 'Источник цитаты', exact: true });
    await expect(source).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Добавить блок', exact: true })).toBeDisabled();
    await source.focus(); await source.press('ArrowDown');
    const popup = page.getByRole('listbox');
    await expect(popup).toBeVisible();
    const target = popup.getByRole('option', { name: 'Исследование качества моделей · 2025', exact: true });
    await target.click();
    await page.getByRole('button', { name: 'Добавить блок', exact: true }).click();
    const text = page.getByRole('textbox', { name: 'Текст блока new_1', exact: true });
    await expect(text).toBeFocused(); await text.fill('Уточнение со ссылкой на источник.');
    expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0); expect(state.requests).toHaveLength(0);
    await expect(page.getByText('DOI: 10.1234/example', { exact: true }).last()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `.work/pdf-citations-${width}.png`, fullPage: true });
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
    await expect.poll(() => state.writes.length).toBe(1);
    expect(state.writes[0].draft.blocks.at(-1)).toMatchObject({ kind: 'citation', source_id: 2, text: 'Уточнение со ссылкой на источник.' });
    expect(state.builds).toHaveLength(0); expect(state.requests).toHaveLength(0);
  });
}

test('PDF unavailable bibliography preserves an existing citation and retries without a write', async ({ page }) => {
  const state = await fixture(page, { sourceFailure: true, blocks: [{ block_id: 'citation', kind: 'citation', text: 'Существующая цитата', source_id: 7 }] });
  await page.getByRole('textbox', { name: 'Текст блока citation', exact: true }).fill('Локальная правка цитаты');
  await expect(page.getByText('Источник 7 · нет в списке', { exact: true })).toBeVisible();
  // Revalidate through the current project owner; no save or paid work is implied.
  await expect(page.getByRole('button', { name: 'Повторить загрузку источников', exact: true })).toBeVisible();
  state.sourceFailure = false; state.sources = [];
  await page.getByRole('button', { name: 'Повторить загрузку источников', exact: true }).click();
  await expect(page.getByText(/пока нет доступных зарегистрированных источников/)).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Текст блока citation', exact: true })).toHaveValue('Локальная правка цитаты');
  expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
});

test('PDF can find a source in a long bibliography without committing a dismissed query', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 600 });
  const state = await fixture(page);
  state.sources = Array.from({ length: 20 }, (_, index) => ({ source_id: index + 1, title: `Источник ${index + 1} — исследование` }));
  const kind = page.getByRole('combobox', { name: 'Тип нового блока', exact: true });
  await kind.fill('Цитирование'); await kind.press('ArrowDown'); await kind.press('Enter');
  const source = page.getByRole('combobox', { name: 'Источник цитаты', exact: true });
  await expect(source).toBeEnabled(); await source.fill('Источник 12');
  const option = page.getByRole('option', { name: 'Источник 12 — исследование', exact: true });
  await expect(option).toBeVisible();
  const control = await source.evaluate((node) => {
    const rect = node.closest('[class*="-control"]').getBoundingClientRect();
    return { width: rect.width, left: rect.left };
  });
  const popup = await page.getByRole('listbox').evaluate((node) => {
    const rect = node.parentElement.getBoundingClientRect();
    return { width: rect.width, left: rect.left };
  });
  expect(Math.abs(control.width - popup.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(control.left - popup.left)).toBeLessThanOrEqual(1);
  await source.press('Escape');
  await expect(page.getByRole('button', { name: 'Добавить блок', exact: true })).toBeDisabled();
  expect(state.writes).toHaveLength(0);
  await source.fill('Источник 12'); await option.click();
  await page.getByRole('button', { name: 'Добавить блок', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Текст блока new_1', exact: true })).toBeFocused();
  expect(state.writes).toHaveLength(0); expect(state.requests).toHaveLength(0);
});

for (const width of [1440, 900, 393, 320]) {
  test(`PDF reviewed block replacements remain readable and keyboard-safe at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 320 ? 568 : 851 });
    const state = await reviewFixture(page);
    const trigger = page.getByRole('button', { name: 'Посмотреть изменения', exact: true });
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: 'Предлагаемые изменения', exact: true });
    await expect(dialog).toContainText('Изменено фрагментов: 6');
    await expect(dialog).toContainText('Заголовок · уровень 1');
    await expect(dialog).toContainText('Заголовок · уровень 2');
    await expect(dialog).toContainText('A | 3');
    await expect(dialog).toContainText('figures/after.png');
    await expect(dialog).toContainText('Источник: 2');
    await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeFocused();
    for (let index = 0; index < 8; index += 1) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
    }
    const comparisons = dialog.getByRole('region', { name: 'Сравнение версий документа', exact: true });
    await comparisons.focus(); await comparisons.press('PageDown');
    await expect.poll(() => comparisons.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
    const apply = dialog.getByRole('button', { name: 'Применить', exact: true });
    const rect = await apply.boundingBox();
    expect(rect.y + rect.height).toBeLessThanOrEqual(page.viewportSize().height);
    expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    await page.screenshot({ path: `.work/pdf-review-${width}.png`, fullPage: true });
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden(); await expect(trigger).toBeFocused();
    expect(state.writes).toHaveLength(0);
    await trigger.click(); await apply.click();
    await expect(page.getByRole('status').filter({ hasText: 'Правки применены. Пересоберите PDF' })).toBeVisible();
    expect(state.writes).toHaveLength(1); expect(state.builds).toHaveLength(0);
    expect(state.writes[0].draft.blocks.find((block) => block.block_id === 'image').asset_path).toBe('figures/after.png');
    expect(state.writes[0].draft.blocks.find((block) => block.block_id === 'citation').source_id).toBe(2);
    expect(state.writes[0].draft.blocks.find((block) => block.block_id === 'closing').text).toBe('Этот фрагмент не изменяется.');
  });
}

test('PDF review can close a slow read and never writes on reject or stale revision', async ({ page }) => {
  let release;
  const state = await reviewFixture(page, { gate: new Promise((resolve) => { release = resolve; }) });
  const trigger = page.getByRole('button', { name: 'Посмотреть изменения', exact: true });
  await trigger.click();
  await expect(page.getByRole('status').filter({ hasText: 'Загружаю правки…' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden(); await expect(trigger).toBeFocused();
  release();
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Изменено фрагментов: 6');
  state.proposal.stale = true;
  await dialog.getByRole('button', { name: 'Обновить просмотр', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
  await expect(dialog).toContainText('Предложение устарело');
  await dialog.getByRole('button', { name: 'Отклонить', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Правки отклонены' })).toBeVisible();
  expect(state.writes).toHaveLength(0); expect(state.leaseAcquisitions).toBe(0);
});

for (const width of [1440, 393, 320]) test(`PDF structural v2 review preserves scope and geometry ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: width === 1440 ? 900 : 568 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const state = await reviewFixture(page);
  const blocks = state.draft.blocks;
  const after = [blocks[2], blocks[0], blocks[1], {
    block_id: 'new_cat_notes', kind: 'paragraph', title: 'Забота о котиках',
    text: 'Добавленный фрагмент остаётся предложением до применения. '.repeat(80),
  }, blocks[3], blocks[4], blocks[6]];
  state.proposal = { ...state.proposal, patch_version: 2,
    draft: { ...state.draft, blocks: after } };
  const trigger = page.getByRole('button', { name: 'Посмотреть изменения', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Предлагаемые изменения', exact: true });
  await expect(dialog).toContainText('Изменено фрагментов: 5');
  await expect(dialog).toContainText('Перемещение · позиция 3 → 1');
  await expect(dialog).toContainText('Блока не было');
  await expect(dialog).toContainText('Блок будет удалён');
  await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeFocused();
  const body = dialog.getByRole('region', { name: 'Сравнение версий документа', exact: true });
  await body.focus(); await body.press('PageDown');
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  const apply = dialog.getByRole('button', { name: 'Применить', exact: true });
  const rect = await apply.boundingBox();
  expect(rect.y + rect.height).toBeLessThanOrEqual(page.viewportSize().height);
  expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.addScriptTag({ content: axe.source });
  expect(await page.evaluate(async () => (await window.axe.run()).violations
    .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
  await page.screenshot({ path: info.outputPath('structure-review.png'), fullPage: true });
  await page.keyboard.press('Escape'); await expect(trigger).toBeFocused();
  expect(state.writes).toHaveLength(0);
  const runs = state.requests.length;
  await trigger.click(); await apply.click();
  await expect(page.getByRole('status').filter({ hasText: 'Правки применены. Пересоберите PDF' })).toBeVisible();
  expect(state.writes).toHaveLength(1); expect(state.builds).toHaveLength(0);
  expect(state.writes[0].draft.blocks).toEqual(after);
  expect(state.requests).toHaveLength(runs);
});

test('PDF invalidation during initial discovery does not reveal a false creation state', async ({ page }) => {
  let releaseWorkspace;
  const workspace = new Promise((resolve) => { releaseWorkspace = resolve; });
  const state = await fixture(page, { readGates: { workspace } });
  try {
    await expect(page.getByText('Загружаю PDF-студию…', { exact: true })).toBeVisible();
    state.socket.send(JSON.stringify({ type: 'status_update', metadata: {
      kind: 'workspace_invalidation', workspace_invalidation: {},
    } }));
    await expect.poll(() => state.factReads.workspace).toBe(2);
    await expect(page.getByText('Загружаю PDF-студию…', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Создать рабочее место для PDF', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
    releaseWorkspace();
    await expect(page.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toBeVisible();
    expect(state.factReads.project).toBe(1); expect(state.factReads.authoring).toBe(1);
    expect(state.activations).toBe(0); expect(state.writes).toEqual([]);
    expect(state.builds).toEqual([]); expect(state.requests).toEqual([]);
  } finally { releaseWorkspace(); }
});

test('slow PDF startup never offers creation before existing project facts arrive', async ({ page }) => {
  let workspaceReady; let projectReady; let authoringReady;
  const readGates = {
    workspace: new Promise((resolve) => { workspaceReady = resolve; }),
    project: new Promise((resolve) => { projectReady = resolve; }),
    authoring: new Promise((resolve) => { authoringReady = resolve; }),
  };
  const state = await fixture(page, { readGates });
  const noCreation = async () => {
    await expect(page.getByRole('button', { name: 'Создать рабочее место для PDF', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  };
  await expect(page.getByText('Загружаю PDF-студию…', { exact: true })).toBeVisible();
  await noCreation();
  workspaceReady();
  await expect(page.getByText('Загружаю PDF-проект…', { exact: true })).toBeVisible();
  await noCreation();
  await expect(page.getByRole('button', { name: 'Собрать черновик', exact: true })).toBeDisabled();
  projectReady();
  await expect(page.getByText('Загружаю содержание документа…', { exact: true })).toBeVisible();
  await noCreation();
  await expect(page.getByRole('button', { name: 'Новое содержание без ИИ', exact: true })).toHaveCount(0);
  authoringReady();
  await expect(page.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toBeVisible();
  expect(state.activations).toBe(0); expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
});

for (const width of [1440, 900, 393, 320]) {
  test(`PDF studio ${width}px keeps document editing, assistant controls and layout`, async ({ page }) => {
    await page.setViewportSize({ width, height: width >= 1100 ? 1024 : 851 });
    const state = await fixture(page);
    const editor = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
    await expect(editor).toBeVisible();
    await editor.fill('Локальная правка, которую нельзя потерять.');
    await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Режим: Авто/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Личность: Без личности/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Модель: Авто/ })).toBeVisible();
    await expect(page.getByText('Кем мне быть?', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Ассистент документа', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Весь документ', { exact: true })).toHaveCount(0);
    expect((await page.getByTestId('pdf-assistant-dock').boundingBox()).height).toBeLessThan(240);
    if (width < 1100) await page.getByRole('button', { name: 'Редактор', exact: true }).click();
    await expect(editor).toHaveValue('Локальная правка, которую нельзя потерять.');
    expect(state.writes).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `.work/pdf-studio-${width}.png`, fullPage: true });
    if (width === 1440) {
      await page.addScriptTag({ content: axe.source });
      const violations = await page.evaluate(async () => (await window.axe.run()).violations.filter((item) => ['serious', 'critical'].includes(item.impact)));
      expect(violations).toEqual([]);
    }
  });
}

test('semantic save is explicit and conflict does not refetch-and-overwrite', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  const state = await fixture(page);
  const editor = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
  await editor.fill('Сохранённая версия');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  await expect(editor).toHaveValue('Сохранённая версия');
  await expect(page.getByRole('button', { name: 'Сохранено', exact: true })).toBeDisabled();
  state.conflict = true;
  await editor.fill('Не терять после конфликта');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Версия документа изменилась' })).toBeVisible();
  await expect(editor).toHaveValue('Не терять после конфликта');
  expect(state.writes).toHaveLength(2);
});


async function revealMaterialFile(panel, path) {
  return revealWorkspaceFile(panel, path, 'documents/paper');
}

for (const width of [1440, 393]) for (const workspaceState of ['unavailable', 'expired']) {
test(`PDF ${workspaceState} workspace retains and exports an unsaved document at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 });
  const state = await fixture(page, { materials: true });
  const title = page.getByRole('textbox', { name: 'Название документа', exact: true });
  await title.fill('Локальный несохранённый документ');
  const path = `**/api/chats/${THREAD}/work`;
  let observedState = workspaceState;
  const failure = route => route.fulfill({ json: {
    contract_version: 2, workspace: { state: observedState, entries: [], revision: '', history: [] },
    room: { state: workspaceState }, library: { state: 'ready', items: state.library },
  } });
  await page.route(path, failure);
  await page.getByRole('button', { name: 'Материалы', exact: true }).click();
  await page.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
  await page.getByRole('button', { name: 'Закрыть панель документа', exact: true }).click();
  await expect(page.getByTestId('pdf-draft-recovery')).toBeVisible();
  await expect(title).toHaveValue('Локальный несохранённый документ');
  const save = page.getByRole('button', { name: 'Сохранить', exact: true });
  await expect(save).toBeDisabled();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать черновик JSON', exact: true }).click();
  const file = await download;
  try {
    expect(file.suggestedFilename()).toBe('gpthub-pdf-draft.json');
    const chunks = [];
    for await (const chunk of await file.createReadStream()) chunks.push(chunk);
    const local = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    expect(local.title).toBe('Локальный несохранённый документ');
    expect(local.blocks).toEqual(state.draft.blocks);
  } finally { await file.delete(); }
  expect(state.writes).toHaveLength(0);
  expect(state.preparations).toHaveLength(0); expect(state.activations).toBe(0);
  await page.screenshot({ path: info.outputPath('pdf-local-draft-recovery.png'), fullPage: true });
  if (workspaceState === 'unavailable') {
    await page.unroute(path, failure);
    await page.getByRole('button', { name: 'Повторить подключение', exact: true }).click();
    await expect(page.getByTestId('pdf-draft-recovery')).toHaveCount(0);
    await expect(title).toHaveValue('Локальный несохранённый документ');
    expect(state.writes).toHaveLength(0);
    await expect(save).toBeEnabled(); await save.click();
    await expect.poll(() => state.writes.length).toBe(1);
    expect(state.writes[0].draft.title).toBe('Локальный несохранённый документ');
  } else {
    observedState = 'absent';
    await page.getByRole('button', { name: 'Повторить подключение', exact: true }).click();
    await expect(title).toHaveValue('Локальный несохранённый документ');
    await expect(save).toBeDisabled();
    expect(state.preparations).toHaveLength(0);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
}

for (const width of [320, 393, 1440]) {
  test(`PDF materials are a compact, keyboard-operable hierarchy at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 851 });
    const state = await fixture(page, { materials: true });
    state.extraFiles.push(
      { path: 'documents', type: 'dir' },
      { path: 'documents/paper/artifacts/263e111ce7ca2747ea9d6281/document.pdf', type: 'file', size: 25000 },
      { path: 'documents/paper/bibliography/references.bib', type: 'file', size: 77 },
      { path: 'documents/paper/content/очень-длинное-полное-название-исходного-файла-документа.tex', type: 'file', size: 120 },
    );
    await page.getByRole('button', { name: 'Материалы', exact: true }).click();
    const panel = page.getByTestId('pdf-materials-panel');
    await panel.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
    const artifacts = panel.getByRole('button', { name: /Результаты сборки/ });
    await expect(artifacts).toHaveAttribute('aria-expanded', 'false');
    await expect(panel.getByText('document.pdf', { exact: true })).toHaveCount(0);
    await expect(panel.getByText('main.tex', { exact: true })).toBeVisible();
    await expect(panel.getByText('documents', { exact: true })).toHaveCount(0);
    const content = panel.getByRole('button', { name: 'documents/paper/content', exact: true });
    await content.focus(); await content.press('Enter');
    await expect(content).toBeFocused();
    const source = panel.getByRole('button', { name: 'documents/paper/content/002-intro.tex', exact: true });
    await expect(source).toBeVisible();
    expect(await source.evaluate((node) => parseFloat(getComputedStyle(node).paddingLeft)))
      .toBeGreaterThan(await content.evaluate((node) => parseFloat(getComputedStyle(node).paddingLeft)));
    await source.focus();
    await expect(panel.getByTestId('workspace-inspected-path').first()).toHaveText('documents/paper/content/002-intro.tex');
    await content.focus(); await content.press('Space');
    await expect(source).toHaveCount(0);
    await panel.getByRole('button', { name: 'Обновить материалы', exact: true }).click();
    await expect(content).toHaveAttribute('aria-expanded', 'false');
    await content.click();
    await expect(panel.getByText('очень-длинное-полное-название-исходного-файла-документа.tex', { exact: true })).toBeVisible();
    expect(await panel.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    await page.screenshot({ path: `.work/pdf-materials-tree-${width}-${testInfo.project.name}.png`, fullPage: true, scale: 'css' });
    expect(state.reads).toEqual([]); expect(state.writes).toEqual([]); expect(state.requests).toEqual([]);
    expect(state.builds).toEqual([]); expect(state.activations).toBe(0);
  });
}

for (const width of [1440, 393]) {
  test(`PDF materials ${width}px reuse Library intake and open the chosen source`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await fixture(page, { materials: true });
    await page.getByRole('button', { name: 'Материалы', exact: true }).click();
    const panel = page.getByTestId('pdf-materials-panel');
    expect(state.activations).toBe(0);
    expect(state.reads).toEqual([]);
    await expect(await revealMaterialFile(panel, 'documents/paper/assets/chart.png')).toBeDisabled();
    await expect(panel.getByRole('tab', { name: 'Библиотека', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Закрыть панель документа', exact: true }).click();
    const library = await openWorkbenchLibrary(page);
    await library.getByRole('button', { name: 'Добавить в рабочее место', exact: true }).click();
    await expect.poll(() => state.copies.length).toBe(1);
    expect(state.copies[0]).toMatchObject({ expected_revision: 'revision-1', fence: 3 });
    const uploadInput = library.getByTestId('work-upload-input');
    // Ответ API копирования ещё не означает, что React снял блокировку загрузки.
    await expect(uploadInput).toBeEnabled();
    await uploadInput.setInputFiles({
      name: 'uploaded.txt', mimeType: 'text/plain', buffer: Buffer.from('Source data'),
    });
    await expect.poll(() => state.uploads.length).toBe(1);
    expect(state.uploads[0]).toContain('upload_intent_id');
    await expect(library.getByTestId('work-library-file').filter({ hasText: 'uploaded.txt' })).toBeVisible();
    // Chakra intentionally pauses toast expiry under the pointer. Move away from
    // the upload/copy area before waiting for the unobstructed visual capture.
    await page.getByRole('dialog').getByText('Библиотека', { exact: true }).hover();
    await expect(page.getByRole('region', { name: 'Notifications-bottom-right' }).getByText('Файл сохранён в библиотеке', { exact: true })).toBeHidden();
    expect(state.extraFiles.some(item => item.path === 'uploaded.txt')).toBe(false);
    await page.screenshot({ path: `.work/pdf-materials-library-${width}.png`, fullPage: true });
    if (width === 393) {
      const actions = library.locator('[data-toast-protected-actions]').first();
      const height = await actions.getByRole('button').evaluate((node) => node.getBoundingClientRect().height);
      expect(height).toBe(34);
      await page.addScriptTag({ content: axe.source });
      expect(await page.evaluate(async () => (await window.axe.run()).violations
        .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    }
    await closeWorkbenchLibrary(page);
    await page.getByRole('button', { name: 'Материалы', exact: true }).click();
    const sharedFiles = panel.getByRole('button', { name: /Общие файлы чата/ });
    await expect(sharedFiles).toHaveAttribute('aria-expanded', 'false');
    await sharedFiles.click();
    await expect(panel.locator('[data-workspace-path="notes.txt"]')).toBeVisible();
    await (await revealMaterialFile(panel, 'documents/paper/content/002-intro.tex')).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const source = page.getByRole('textbox', { name: 'Содержимое documents/paper/content/002-intro.tex', exact: true });
    await expect(source).toHaveValue('Source of documents/paper/content/002-intro.tex');
    await expect(source).toBeFocused();
    await page.getByRole('button', { name: 'Содержание', exact: true }).click();
    await page.getByRole('button', { name: 'LaTeX', exact: true }).click();
    await expect(source).toBeVisible();
    expect(state.reads).toEqual(['documents/paper/content/002-intro.tex']);
    expect(state.writes).toHaveLength(0);
    expect(state.requests).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

for (const width of [1440, 393, 320]) {
  test(`PDF Library image becomes a project figure with explicit insertion and no generation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await fixture(page, { materials: true });
    state.library.push({ file_id: '12345678-1234-1234-1234-123456789abc', name: 'chart.png', availability: 'ready', file_type: 'image/png' });
    state.extraFiles.push({ path: 'documents/other/figures/foreign.png', type: 'file', size: 100 });
    const panel = await openWorkbenchLibrary(page, { project: true, refresh: true });
    const addImage = panel.getByRole('button', { name: 'Добавить chart.png в PDF-проект', exact: true });
    await addImage.click();
    await expect(panel.getByRole('status').filter({ hasText: 'Файл в проекте' })).toBeVisible();
    await expect(addImage).toBeEnabled();
    expect(state.copies).toHaveLength(1);
    expect(state.copies[0]).toMatchObject({ document_path: 'documents/paper', expected_revision: 'revision-1', fence: 3 });
    expect(state.writes).toHaveLength(0); expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
    await addImage.click(); await expect(addImage).toBeEnabled();
    await expect(panel.getByRole('status').filter({ hasText: 'Файл уже в проекте' })).toBeVisible();
    expect(state.extraFiles.filter((item) => item.path.endsWith('library_12345678123412341234123456789abc.png'))).toHaveLength(1);
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run()).violations.filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    await page.keyboard.press('Escape');
    const types = page.getByRole('combobox', { name: 'Тип нового блока', exact: true });
    await types.click(); await page.getByRole('option', { name: 'Изображение', exact: true }).click();
    await page.getByRole('button', { name: 'Добавить блок', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Заголовок блока new_1', exact: true })).toBeFocused();
    const image = page.getByRole('combobox', { name: 'Изображение блока new_1', exact: true });
    await page.keyboard.press('Tab'); await expect(image).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(page.getByRole('option', { name: 'foreign.png', exact: true })).toHaveCount(0);
    await page.getByRole('option', { name: 'chart.png', exact: true }).click();
    await page.getByRole('textbox', { name: 'Заголовок блока new_1', exact: true }).fill('Проверенные данные эксперимента');
    await page.screenshot({ path: `.work/pdf-image-insert-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
    await expect.poll(() => state.writes.length).toBe(1);
    expect(state.writes[0].expected_revision).toBe('revision-2');
    expect(state.writes[0].draft.blocks.at(-1)).toMatchObject({ kind: 'figure', asset_path: 'figures/library_12345678123412341234123456789abc.png', title: 'Проверенные данные эксперимента' });
    expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
  });
}

test('PDF image intake conflict stays explicit and never inserts or retries automatically', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  const state = await fixture(page);
  state.library.push({ file_id: '12345678-1234-1234-1234-123456789abc', name: 'chart.png', availability: 'ready' });
  state.assetConflict = true;
  const panel = await openWorkbenchLibrary(page, { project: true, refresh: true });
  await panel.getByRole('button', { name: 'Добавить chart.png в PDF-проект', exact: true }).click();
  await expect(panel.getByRole('status').filter({ hasText: 'Проект изменился' })).toBeVisible();
  expect(state.copies).toHaveLength(1); expect(state.extraFiles).toHaveLength(0);
  expect(state.writes).toHaveLength(0); expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
});

test('PDF materials protect semantic drafts and expose source read failure without losing them', async ({ page }) => {
  const state = await fixture(page, { materials: true });
  const content = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
  await content.fill('Локальные несохранённые правки');
  await page.getByRole('button', { name: 'Материалы', exact: true }).click();
  const panel = page.getByTestId('pdf-materials-panel');
  await page.getByRole('button', { name: 'Закрыть панель документа', exact: true }).click();
  const library = await openWorkbenchLibrary(page);
  await expect(library.getByRole('button', { name: 'Добавить в рабочее место', exact: true })).toBeDisabled();
  await closeWorkbenchLibrary(page);
  await page.getByRole('button', { name: 'Материалы', exact: true }).click();
  await (await revealMaterialFile(panel, 'documents/paper/content/002-intro.tex')).click();
  await expect(page.getByRole('alertdialog')).toBeVisible();
  expect(state.reads).toEqual([]);
  await page.getByRole('alertdialog').getByRole('button', { name: 'Продолжить редактирование', exact: true }).click();
  await page.getByRole('button', { name: 'Закрыть панель документа', exact: true }).click();
  await expect(content).toHaveValue('Локальные несохранённые правки');
  await page.getByRole('button', { name: 'Отменить правки', exact: true }).click();
  state.readFailure = true;
  await page.getByRole('button', { name: 'Материалы', exact: true }).click();
  await (await revealMaterialFile(panel, 'documents/paper/content/002-intro.tex')).click();
  await expect(panel.getByRole('alert')).toContainText('Не удалось открыть исходник');
  await page.getByRole('button', { name: 'Закрыть панель документа', exact: true }).click();
  await expect(content).toBeVisible();
  expect(state.writes).toHaveLength(0);
});

test('PDF source transition waits for explicit discard even when the file is already open', async ({ page }) => {
  const state = await fixture(page, { materials: true });
  const chooseSource = async () => {
    await page.getByRole('button', { name: 'Материалы', exact: true }).click();
    await (await revealMaterialFile(page.getByTestId('pdf-materials-panel'), 'documents/paper/content/002-intro.tex')).click();
  };
  await chooseSource();
  const source = page.getByRole('textbox', { name: 'Содержимое documents/paper/content/002-intro.tex', exact: true });
  await expect(source).toBeVisible();
  await page.getByRole('button', { name: 'Содержание', exact: true }).click();
  await page.getByRole('textbox', { name: 'Текст блока intro', exact: true }).fill('Правка до явного отказа');
  await chooseSource();
  await expect(page.getByRole('alertdialog')).toBeVisible();
  expect(state.reads).toHaveLength(1);
  await page.getByRole('alertdialog').getByRole('button', { name: 'Отбросить и перейти', exact: true }).click();
  await expect(source).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(state.reads).toHaveLength(1);
  expect(state.writes).toHaveLength(0);
});

test('PDF Library upload is Library-only and does not claim workspace insertion', async ({ page }) => {
  const state = await fixture(page, { materials: true });
  const panel = await openWorkbenchLibrary(page);
  await panel.getByTestId('work-upload-input').setInputFiles({
    name: 'uploaded.txt', mimeType: 'text/plain', buffer: Buffer.from('Source data'),
  });
  await expect(panel.getByTestId('work-library-outcome')).toHaveText('сохранён в библиотеке');
  await expect(panel.locator('[data-workspace-path="uploaded.txt"]')).toHaveCount(0);
  await expect(panel.getByTestId('work-library-file').filter({ hasText: 'uploaded.txt' })).toBeVisible();
  await expect(panel.getByTestId('work-library-file').filter({ hasText: 'uploaded.txt' })).toContainText('сохранён в библиотеке');
  expect(state.uploads).toHaveLength(1);
  expect(state.extraFiles.some(item => item.path === 'uploaded.txt')).toBe(false);
  expect(state.copies).toHaveLength(0);
  expect(state.requests).toHaveLength(0);
});

for (const width of [1440, 393]) {
test(`formatting ${width}px is project-specific without duplicate authoring or creation`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 1440 ? 1024 : 851 });
  await fixture(page);
  const composer = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await composer.fill('Черновик запроса без отправки');
  await page.getByRole('button', { name: 'Оформление', exact: true }).click();
  const panel = page.getByRole('dialog');
  await expect(panel.getByText('Параметры документа', { exact: true })).toBeVisible();
  if (width === 393) {
    const closeControl = panel.getByRole('button', { name: 'Закрыть панель документа', exact: true });
    await expect(closeControl).toHaveCSS('width', '44px');
    await expect(closeControl).toHaveCSS('height', '44px');
    const close = await closeControl.boundingBox();
    // Дробное смещение Drawer в WebKit даёт погрешность порядка0,00003CSSpx.
    expect(Math.round(close.width * 1000) / 1000).toBeGreaterThanOrEqual(44);
    expect(Math.round(close.height * 1000) / 1000).toBeGreaterThanOrEqual(44);
  }
  await expect(panel.getByLabel('Профиль PDF-документа')).toBeVisible();
  const profile = panel.getByRole('combobox', { name: 'Профиль PDF-документа', exact: true });
  await profile.focus(); await profile.press('ArrowDown');
  const formatOption = panel.getByRole('option', { name: /Презентация/ });
  await expect(formatOption).toBeVisible();
  await formatOption.click();
  await expect(panel.getByRole('button', { name: 'Создать проект с профилем', exact: true })).toBeEnabled();
  await expect(panel.getByText('Шаблон издателя', { exact: true })).toBeVisible();
  await expect(panel.getByText('Document Forge', { exact: true })).toHaveCount(0);
  await expect(panel.getByText('Структурированный документ', { exact: true })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: 'Собрать черновик', exact: true })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: 'Проверить финал', exact: true })).toHaveCount(0);
  await page.screenshot({ path: `.work/pdf-studio-formatting-${width}.png`, fullPage: true });
  await panel.getByRole('button', { name: 'Закрыть панель документа' }).click();
  await expect(composer).toHaveValue('Черновик запроса без отправки');
  await expect(page.getByRole('button', { name: 'Оформление', exact: true })).toBeFocused();
});
}

test('an empty existing workspace automatically gets its first PDF project', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  const state = await fixture(page, { noProject: true });
  await expect(page.getByRole('textbox', { name: 'Название документа', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Оформление', exact: true })).toBeEnabled();
  await expect(page.getByText('Document Forge', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Кем мне быть?', { exact: true })).toHaveCount(0);
  expect(state.activations).toBe(0);
  expect(state.writes).toHaveLength(0);
  expect(state.preparations).toEqual([{}]);
});

test('PDF entry prepares a first project but Chat entry and mode choices never allocate', async ({ page }) => {
  const state = await fixture(page, { absent: true, initialSurface: 'chat' });
  expect(state.preparations).toHaveLength(0);
  await page.getByRole('button', { name: 'PDF', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Название документа', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать рабочее место для PDF' })).toHaveCount(0);
  expect(state.preparations).toEqual([{}]);
  expect(state.activations).toBe(0);
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.getByRole('button', { name: 'Режим: Авто', exact: true }).click();
  await expect(page.getByRole('option', { name: /^Авто/ })).toBeVisible();
  await expect(page.getByRole('option', { name: /Презентация/ })).toHaveCount(0);
  expect(state.preparations).toHaveLength(1);
});

test('slow or unconfirmed PDF preparation never flashes manual creation or replays automatically', async ({ page }, info) => {
  let finish;
  const gate = new Promise(resolve => { finish = resolve; });
  const state = await fixture(page, { absent: true, readGates: { prepare: gate } });
  await expect(page.getByText('Готовлю первый PDF-проект…', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать рабочее место для PDF', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
  expect(state.preparations).toHaveLength(1);
  state.prepareFailure = true; state.prepareStatus = 404; finish();
  await expect(page.getByRole('alert').filter({ hasText: 'Подготовка PDF-проекта пока не подтверждена.' })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}\\?surface=pdf$`));
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.getByRole('button', { name: 'PDF', exact: true }).click();
  expect(state.preparations).toHaveLength(1);
  state.prepareFailure = false;
  await page.getByRole('button', { name: 'Повторить подготовку', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Название документа', exact: true })).toBeVisible();
  expect(state.preparations).toHaveLength(2);
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'Название документа', exact: true })).toBeVisible();
  expect(state.preparations).toHaveLength(2);
  expect(state.activations).toBe(0);
  expect(state.requests).toHaveLength(0); expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('pdf-first-project.png'), fullPage: true });
});

test('expired PDF offers an explicit new presentation instead of a dead reload action', async ({ page }, info) => {
  let finish;
  const gate = new Promise(resolve => { finish = resolve; });
  const state = await fixture(page, { absent: true, readGates: { prepare: gate } });
  await expect.poll(() => state.preparations.length).toBe(1);
  state.prepareExpired = true; finish();
  await expect(page.getByRole('alert').filter({ hasText: 'Среда PDF завершена.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Повторить загрузку', exact: true })).toHaveCount(0);
  expect(state.preparations).toHaveLength(1);
  expect(state.activations).toBe(0);
  expect(state.writes).toHaveLength(0);
  await page.getByRole('button', { name: 'Новый документ', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Новый документ', exact: true });
  await expect(dialog).toContainText('Будет создана новая среда');
  expect(state.activations).toBe(0);
  await dialog.getByText('Документ', { exact: true }).click();
  await page.getByRole('option', { name: 'Презентация', exact: true }).click();
  await dialog.getByRole('button', { name: 'Создать документ', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(state.activations).toBe(1);
  expect(state.createdProjects).toHaveLength(1);
  expect(state.createdProjects[0]).toMatchObject({ profile_id: 'beamer_presentation', expected_revision: 'new-workspace-revision' });
  expect(state.builds).toHaveLength(0); expect(state.requests).toHaveLength(0);
  await page.screenshot({ path: info.outputPath('pdf-expired-new-presentation.png'), animations: 'disabled' });
});

async function startDocumentRun(page, state, text = 'Уточни введение документа') {
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill(text);
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => state.requests.length).toBe(1);
  state.socket.send(JSON.stringify({ type: 'job_created', job_id: 'pdf-job-1', celery_task_id: 'pdf-task-1', document_project: PROJECT }));
  await expect(input).toBeHidden();
  await expect(page.getByRole('region', { name: 'Выполнение запроса документа' })).toBeVisible();
}

for (const width of [1440, 393]) test(`PDF first cat slide ${width}px can be reviewed and applied to the open presentation`, async ({ page }) => {
  await page.setViewportSize({ width, height: 851 });
  const blocks = [
    { block_id: 'slide_1', kind: 'slide', title: 'Первый слайд', text: 'Шаблон' },
    { block_id: 'slide_2', kind: 'slide', title: 'Далее', text: 'Не менять' },
  ];
  const state = await fixture(page, { presentation: true, title: 'Новая презентация', blocks });
  state.proposal = { proposal_id: PROPOSAL, path: 'documents/paper', stale: false,
    expected_revision: state.revision, authoring_version: 1, draft_digest: 'a'.repeat(64),
    before: state.draft, draft: { ...state.draft, blocks: [
      { ...blocks[0], title: 'Мир котиков', text: 'Пушистые друзья рядом с нами' }, blocks[1],
    ] } };
  await startDocumentRun(page, state, 'Презентация о котиках, создай черновик первого слайда');
  expect(state.requests[0].document_context).toMatchObject({ path: 'documents/paper', authoring_version: 1 });
  state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Правки первого слайда готовы к просмотру.',
    metadata: { execution_status: 'completed', document_project: PROJECT, document_proposal: PROPOSAL } }));
  await page.getByRole('button', { name: 'Посмотреть изменения', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Предлагаемые изменения', exact: true });
  await expect(dialog).toContainText('Мир котиков');
  expect(state.writes).toHaveLength(0);
  await dialog.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Правки применены. Пересоберите PDF' })).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0].draft.blocks[0]).toMatchObject({ block_id: 'slide_1', title: 'Мир котиков' });
  expect(state.writes[0].draft.blocks[1]).toEqual(blocks[1]);
  expect(state.builds).toHaveLength(0);
  expect(state.activations).toBe(0);
});

for (const [width, height] of [[1440, 700], [393, 568], [393, 360]]) {
  test(`PDF trace has a closed frame and internal scroll at ${width}x${height}`, async ({ page, isMobile }, info) => {
    await page.setViewportSize({ width, height });
    const state = await fixture(page);
    await startDocumentRun(page, state);
    const sendSteps = count => {
      for (let i = 0; i < count; i += 1) state.socket.send(JSON.stringify({
        type: 'status_update', job_id: 'pdf-job-1', timestamp: new Date().toISOString(), metadata: {
          kind: 'document_status', document_status: { stage: i % 2 ? 'outline' : 'section_authoring', status: 'running' },
        },
      }));
    };
    sendSteps(12);
    const dock = page.getByTestId('pdf-assistant-dock');
    const card = page.getByTestId('workbench-trace-card');
    const scroll = page.getByRole('region', { name: 'Этапы выполнения', exact: true });
    await expect(scroll).toBeVisible();
    await expect(card).toHaveCSS('box-shadow', 'none');
    const header = card.getByRole('button', { name: /Ход работы/ });
    const initial = { dock: await dock.boundingBox(), card: await card.boundingBox(), header: await header.boundingBox() };
    sendSteps(48);
    await expect(card.getByText('Написание разделов: выполняется').first()).toBeAttached();
    await expect.poll(() => scroll.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
    expect(await dock.boundingBox()).toEqual(initial.dock);
    expect(await card.boundingBox()).toEqual(initial.card);
    const bounds = await card.boundingBox();
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(initial.dock.y + initial.dock.height - 5);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(height);
    if (isMobile) {
      // Mobile WebKit has no mouse-wheel API. Verify the same accessible
      // internal scroller with keyboard input; native touch needs device acceptance.
      await scroll.focus(); await page.keyboard.press('PageDown');
    } else {
      await scroll.hover(); await page.mouse.wheel(0, 1200);
    }
    await expect.poll(() => scroll.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
    expect(await header.boundingBox()).toEqual(initial.header);
    expect(await dock.boundingBox()).toEqual(initial.dock);
    await scroll.focus(); await page.keyboard.press(isMobile ? 'End' : 'Control+End');
    await expect(scroll).toBeFocused();
    await expect.poll(() => scroll.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThan(2);
    await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeInViewport();
    await page.screenshot({ path: info.outputPath('pdf-contained-trace.png'), animations: 'disabled' });
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run(document.querySelector('[data-testid="document-assistant-activity"]')))
      .violations.filter(item => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
    expect(state.requests).toHaveLength(1);
    state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Готово.',
      metadata: { execution_status: 'completed', document_project: PROJECT } }));
    await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
    const draftInput = page.getByRole('textbox', { name: 'Сообщение', exact: true });
    await draftInput.fill('Не потерять следующий запрос');
    await page.getByRole('button', { name: 'Этапы', exact: true }).click();
    await expect(draftInput).toBeHidden();
    await expect(scroll).toBeVisible();
    const completed = await card.boundingBox();
    expect(completed.y + completed.height).toBeLessThanOrEqual(height);
    await card.getByRole('button', { name: 'Ход работы', exact: true }).click();
    await expect(card).toHaveCount(0);
    await expect(draftInput).toBeVisible();
    await expect(draftInput).toHaveValue('Не потерять следующий запрос');
    await expect(draftInput).toBeFocused();
    expect(state.requests).toHaveLength(1);
  });
}

for (const width of [1440, 393]) {
  test(`PDF ${width}px swaps composer for the same trace and restores it on completion`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await fixture(page);
    await startDocumentRun(page, state);
    state.socket.send(JSON.stringify({ type: 'status_update', job_id: 'pdf-job-1', metadata: {
      kind: 'document_status', document_status: { stage: 'section_authoring', status: 'running' },
    } }));
    await expect(page.getByText('Написание разделов: выполняется').first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
    expect((await page.getByRole('button', { name: 'Остановить генерацию', exact: true }).boundingBox()).height).toBe(34);
    expect((await page.getByRole('button', { name: 'Открыть в Чате', exact: true }).boundingBox()).height).toBe(34);
    await page.screenshot({ path: `.work/pdf-assistant-running-${width}.png`, fullPage: true });
    if (width === 1440) {
      await page.addScriptTag({ content: axe.source });
      expect(await page.evaluate(async () => (await window.axe.run()).violations.filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    }
    state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Предложение правки документа готово.',
      metadata: { execution_status: 'completed', document_project: PROJECT } }));
    const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
    await expect(input).toBeVisible();
    await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toHaveCount(0);
    await expect(page.getByText('Предложение правки документа готово.', { exact: true })).toHaveCount(0);
    await input.fill('Следующий запрос, пока без отправки');
    await page.getByRole('button', { name: 'Открыть в Чате', exact: true }).click();
    await expect(page.getByText('Предложение правки документа готово.', { exact: true })).toBeVisible();
    await expect(input).toHaveValue('Следующий запрос, пока без отправки');
    await page.getByRole('button', { name: 'PDF', exact: true }).click();
    await expect(input).toHaveValue('Следующий запрос, пока без отправки');
    expect(state.requests).toHaveLength(1);
  });
}

for (const decision of ['accept', 'decline', 'expire']) {
  test(`PDF confirmation ${decision} keeps the original anchored run without another user message`, async ({ page }) => {
    await page.setViewportSize({ width: 393, height: 851 });
    const state = await fixture(page);
    await startDocumentRun(page, state);
    const offer = { offer_id: 'pdf-offer-1', mode: 'deep_research', label: 'Исследование для документа',
      offer_kind: 'tool', blocking: true, offered_at: new Date().toISOString(), expires_in_sec: decision === 'expire' ? 2 : 60 };
    state.socket.send(JSON.stringify({ type: 'status_update', job_id: 'pdf-job-1', metadata: { kind: 'mode_offer', mode_offer: offer } }));
    state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Нужно ваше решение.',
      metadata: { awaiting_confirmation: true, mode_offer: offer } }));
    const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
    if (decision === 'expire') {
      await expect(input).toBeVisible({ timeout: 8000 });
      await expect(page.getByText('Срок подтверждения истёк. Платный запуск не начат.', { exact: true })).toBeVisible();
      expect(state.requests).toHaveLength(1);
      return;
    }
    await expect(input).toBeHidden();
    await page.getByRole('button', { name: decision === 'accept' ? 'Использовать' : 'Продолжить без этого', exact: true }).click();
    await expect.poll(() => state.requests.length).toBe(2);
    expect(state.requests[1].confirm_offer_id).toBe('pdf-offer-1');
    if (decision === 'decline') expect(state.requests[1].confirmation_decision).toBe('decline');
    await expect(input).toBeHidden();
    expect(state.requests[1].text).toBe('');
  });
}

test('PDF Stop restores input without an automatic retry', async ({ page }) => {
  const state = await fixture(page);
  await startDocumentRun(page, state);
  await page.getByRole('button', { name: 'Остановить генерацию', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
  expect(state.requests).toHaveLength(1);
});

test('sidebar footer and input have independent natural heights through input growth and surface changes', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fixture(page);
  const footer = page.locator('[data-chat-sidebar-footer]');
  expect(await footer.evaluate((node) => getComputedStyle(node).borderTopWidth)).toBe('0px');
  const baseline = await footer.boundingBox();
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await expect(page.getByRole('button', { name: 'Модель: Авто', exact: true })).toHaveCSS('height', '34px');
  const short = await page.locator('[data-composer-container]').boundingBox();
  await footer.evaluate((node) => { node.style.paddingTop = '80px'; });
  await expect.poll(async () => (await page.locator('[data-composer-container]').boundingBox()).height).toBe(short.height);
  await footer.evaluate((node) => node.style.removeProperty('padding-top'));
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill(Array(12).fill('Строка длинного запроса').join('\n'));
  await expect.poll(async () => (await page.locator('[data-composer-container]').boundingBox()).height).toBeGreaterThan(short.height);
  expect((await footer.boundingBox()).height).toBe(baseline.height);
  await page.getByRole('button', { name: 'PDF', exact: true }).click();
  await expect(input).toHaveValue(Array(12).fill('Строка длинного запроса').join('\n'));
  expect((await footer.boundingBox()).height).toBe(baseline.height);
  await page.setViewportSize({ width: 1200, height: 600 });
  expect((await footer.boundingBox()).height).toBe(baseline.height);
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('');
  await page.screenshot({ path: '.work/sidebar-composer-independent.png', fullPage: true });
});

test('sidebar navigation never shrinks or moves during PDF admission, trace and completion', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const state = await fixture(page);
  const footer = page.locator('[data-chat-sidebar-footer]');
  const controls = footer.getByRole('button');
  const geometry = () => controls.evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect();
    return { y: rect.y, height: rect.height, font: getComputedStyle(node).fontSize };
  }));
  await expect(controls).toHaveCount(4);
  await page.getByRole('button', { name: 'Работа PDF и расход кредитов', exact: true }).click();
  await expect(page.getByTestId('pdf-tools-consent-notice')).toContainText('могут расходовать кредиты');
  await page.keyboard.press('Escape');
  const baseline = await geometry();
  expect(baseline.map((item) => item.height)).toEqual([34, 34, 34, 34]);
  const stable = async () => expect.poll(geometry).toEqual(baseline);
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Уточни введение');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => state.requests.length).toBe(1);
  await expect(page.getByRole('region', { name: 'Выполнение запроса документа' })).toBeVisible();
  await stable();
  const independent = () => expect(footer).toHaveCSS('border-top-width', '0px');
  await independent();
  await page.screenshot({ path: '.work/pdf-sidebar-pending-job-stable.png', fullPage: true });
  state.socket.send(JSON.stringify({ type: 'job_created', job_id: 'pdf-job-1', celery_task_id: 'pdf-task-1', document_project: PROJECT }));
  state.socket.send(JSON.stringify({ type: 'status_update', job_id: 'pdf-job-1', metadata: {
    kind: 'document_status', document_status: { stage: 'section_authoring', status: 'running' },
  } }));
  await expect(page.getByText('Написание разделов: выполняется').first()).toBeVisible();
  await stable(); await independent();
  state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Готово',
    metadata: { execution_status: 'completed', document_project: PROJECT } }));
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
  await stable(); await independent();
});

test('PDF auto-growing fields resize without ResizeObserver errors', async ({ page }, info) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.__resizeErrors = [];
    window.__resizeWrites = [];
    window.addEventListener('error', event => {
      if (event.message.includes('ResizeObserver')) window.__resizeErrors.push(event.message);
    });
    const NativeObserver = window.ResizeObserver;
    window.ResizeObserver = class extends NativeObserver {
      constructor(callback) {
        super((entries, observer) => {
          const mutations = new MutationObserver(() => {});
          entries.filter(entry => entry.target.tagName === 'TEXTAREA').forEach(entry => {
            mutations.observe(entry.target, { attributes: true, attributeFilter: ['style'] });
          });
          try { callback.call(observer, entries, observer); }
          finally {
            window.__resizeWrites.push(...mutations.takeRecords().map(record => record.target.getAttribute('aria-label')));
            mutations.disconnect();
          }
        });
      }
    };
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  const state = await fixture(page);
  const input = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
  const text = 'Длинный абзац для проверки переноса строк. '.repeat(90);
  await input.fill(text);
  for (const width of [1000, 600, 393, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(input).toHaveValue(text);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (width === 393) await page.screenshot({ path: info.outputPath('pdf-resize-narrow.png'), animations: 'disabled' });
  }
  await input.fill('Короткий текст');
  await expect.poll(async () => (await input.boundingBox()).height).toBeLessThan(100);
  expect(await page.evaluate(() => window.__resizeErrors)).toEqual([]);
  expect(await page.evaluate(() => window.__resizeWrites)).toEqual([]);
  expect(errors).toEqual([]);
  expect(state.writes).toHaveLength(0);
});

test('document-like fields grow without blank section boxes and structure navigation preserves edits', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  const state = await fixture(page);
  await expect(page.getByRole('textbox', { name: 'Текст блока heading', exact: true })).toHaveCount(0);
  const input = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
  const before = await input.boundingBox();
  await input.fill(Array(20).fill('Длинный абзац для проверки роста поля.').join('\n'));
  await expect.poll(async () => (await input.boundingBox()).height).toBeGreaterThan(before.height);
  expect((await input.boundingBox()).height).toBeLessThanOrEqual(321);
  await page.getByRole('button', { name: 'Структура', exact: true }).click();
  const outline = page.getByRole('dialog');
  await expect(outline.getByText('Структура документа', { exact: true })).toBeVisible();
  await outline.getByRole('button', { name: /Неизменяемый заключительный раздел/ }).click();
  await expect(page.getByRole('textbox', { name: 'Текст блока closing', exact: true })).toBeFocused();
  await expect(input).toHaveValue(Array(20).fill('Длинный абзац для проверки роста поля.').join('\n'));
  expect(state.writes).toHaveLength(0);
});

test('mobile PDF toolbar retains all actions within two compact rows', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 851 });
  await fixture(page);
  const toolbar = page.getByTestId('pdf-studio-toolbar');
  await expect(toolbar.getByRole('button', { name: 'Материалы', exact: true })).toBeVisible();
  await expect(toolbar.getByRole('button', { name: 'Оформление', exact: true })).toBeVisible();
  await expect(toolbar.getByRole('button', { name: 'Собрать черновик', exact: true })).toBeVisible();
  await expect(toolbar.getByRole('button', { name: 'Проверить финал', exact: true })).toBeVisible();
  expect((await toolbar.boundingBox()).height).toBeLessThan(116);
  for (const label of ['Собрать черновик', 'Проверить финал']) {
    expect(await toolbar.getByRole('button', { name: label, exact: true })
      .evaluate((button) => button.scrollWidth <= button.clientWidth)).toBe(true);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '.work/pdf-studio-mobile-toolbar-final.png', fullPage: true });
});

for (const width of [1440, 393, 320]) {
  test(`PDF build status and Open PDF remain visible outside checks at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await fixture(page, { sourceDigest: 'b'.repeat(64) });
    const checks = page.getByTestId('pdf-checks-bar');
    await page.getByRole('button', { name: 'Собрать черновик', exact: true }).click();
    const activity = page.getByTestId('pdf-build-activity');
    await expect(activity.getByRole('status')).toHaveText('Сборка PDF в очереди');
    await expect(page.getByTestId('pdf-studio-toolbar').locator('.chakra-spinner')).toHaveCount(0);
    await expect(activity.locator('.chakra-spinner')).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Отменить сборку', exact: true })).toBeVisible();
    await expect(checks.getByRole('button', { name: 'Проверки', exact: true, includeHidden: true })).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toBeEditable();
    state.build = { ...state.build, state: 'building' };
    await expect(activity.getByRole('status')).toHaveText('Собираю PDF…');
    state.build = { ...state.build, state: 'preview_ready', source_digest: 'b'.repeat(64), artifacts: [{ role: 'pdf', artifact_id: 'visible-pdf' }] };
    const toolbar = page.getByTestId('pdf-studio-toolbar');
    const open = toolbar.getByRole('button', { name: 'Открыть PDF', exact: true });
    await expect(open).toBeVisible();
    await expect(open).toHaveAttribute('data-action-hint', 'idle');
    await expect(activity.getByRole('status')).toHaveText('Черновик готов');
    await expect(page.getByText('Черновик готов', { exact: true })).toHaveCount(1);
    if (width >= 1100) await expect(page.getByTestId('pdf-preview-header')).toContainText('Черновик готов');
    await open.click();
    await expect(page.locator('iframe[title="Предпросмотр PDF"]:visible')).toHaveAttribute('src', /^blob:/);
    await expect(toolbar.getByRole('button', { name: 'Обновить PDF', exact: true })).toBeVisible();
    await expect(toolbar.getByRole('button', { name: 'Обновить PDF', exact: true })).not.toHaveAttribute('data-action-hint');
    await expect(toolbar.getByRole('button', { name: 'Открыть PDF', exact: true })).toHaveCount(0);
    await expect(activity.getByRole('button')).toHaveCount(0);
    const buildButton = toolbar.getByRole('button', { name: 'Собрать черновик', exact: true });
    expect(Math.abs((await toolbar.getByRole('button', { name: 'Обновить PDF', exact: true }).boundingBox()).y
      - (await buildButton.boundingBox()).y)).toBeLessThanOrEqual(1);
    expect(await buildButton.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await expect(checks.getByRole('button', { name: 'Проверки', exact: true })).toHaveAttribute('aria-expanded', 'false');
    expect(state.builds).toHaveLength(1);
    expect(state.requests).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `.work/pdf-build-visible-${width}.png`, fullPage: true });
  });
}

for (const width of [1440, 393]) {
  test(`PDF build survives lease invalidation during admission at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let admit;
    const admission = new Promise((resolve) => { admit = resolve; });
    const state = await fixture(page, { readGates: { buildAdmission: admission } });
    try {
      await page.getByRole('button', { name: 'Собрать черновик', exact: true }).click();
      await expect.poll(() => state.builds.length).toBe(1);
      state.socket.send(JSON.stringify({ type: 'status_update', metadata: {
        kind: 'workspace_invalidation', workspace_invalidation: { action: 'lease_acquired', revision_changed: false },
      } }));
      await expect.poll(() => state.factReads.project).toBe(2);
      admit();
      const activity = page.getByTestId('pdf-build-activity').getByRole('status');
      await expect(activity).toHaveText('Сборка PDF в очереди');
      state.build = { ...state.build, state: 'preview_ready', artifacts: [{ role: 'pdf', artifact_id: 'visible-pdf' }] };
      await expect(activity).toHaveText('Черновик готов');
      await expect(page.getByRole('button', { name: 'Собрать черновик', exact: true })).toBeEnabled();
      await expect(page.getByRole('button', { name: 'Открыть PDF', exact: true })).toBeVisible();
      expect(state.builds).toHaveLength(1);
      expect(state.requests).toHaveLength(0);
    } finally { admit(); }
  });
}

for (const width of [1440, 393, 320]) {
  test(`account menu links Chat IDE PDF within the current thread at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 851 });
    const state = await fixture(page);
    const trigger = page.getByRole('button', { name: 'Меню аккаунта', exact: true });
    await trigger.click();
    const menu = page.getByTestId('header-user-menu');
    const peers = { Чат: `/chat/${THREAD}`, IDE: `/chat/${THREAD}?surface=work`, PDF: `/chat/${THREAD}?surface=pdf` };
    for (const [label, href] of Object.entries(peers)) {
      const item = menu.getByRole('menuitem', { name: label, exact: true });
      await expect(item).toHaveAttribute('href', href);
      await expect.poll(async () => (await item.boundingBox()).height).toBe(34);
    }
    await expect(menu.locator('[aria-current="page"]')).toHaveText('PDF');
    expect((await menu.boundingBox()).width).toBeLessThanOrEqual(width - 32);
    await page.screenshot({ path: `.work/account-menu-${width}.png`, fullPage: true });
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    await trigger.click();
    await menu.getByRole('menuitem', { name: 'IDE', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}\\?surface=work$`));
    await trigger.click();
    await expect(menu.locator('[aria-current="page"]')).toHaveText('IDE');
    await menu.getByRole('menuitem', { name: 'PDF', exact: true }).click();
    await expect(page.getByTestId('pdf-studio')).toBeVisible();
    expect(state.activations).toBe(0); expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
    const editor = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
    await editor.fill('Не терять при переходе через меню');
    await trigger.click();
    await menu.getByRole('menuitem', { name: 'Чат', exact: true }).click();
    const guard = page.getByRole('alertdialog');
    await expect(guard).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(editor).toHaveValue('Не терять при переходе через меню');
    await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}\\?surface=pdf$`));
  });
}

for (const width of [1440, 393, 320]) {
  test(`one global Library works from Chat without navigation or duplicate reads at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 851 });
    const state = await fixture(page, { initialSurface: 'chat', materials: true });
    expect(state.factReads.workspace).toBe(0);
    const library = await openWorkbenchLibrary(page);
    await expect(library.getByTestId('work-library-file')).toHaveCount(1);
    await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}$`));
    expect(state.factReads.workspace).toBe(1);
    await expect(library.getByRole('link', { name: 'Скачать notes.txt', exact: true })).toHaveAttribute('href', /\/api\/service\/files\/v1\//);
    for (const button of await library.getByRole('button').all()) {
      const text = await button.textContent();
      if (text.trim() === 'Добавить') expect((await button.boundingBox()).height).toBe(34);
    }
    await page.screenshot({ path: `.work/global-library-${width}.png`, fullPage: true });
    await page.addScriptTag({ content: axe.source });
    expect(await page.evaluate(async () => (await window.axe.run()).violations
      .filter((item) => ['serious', 'critical'].includes(item.impact)))).toEqual([]);
    await closeWorkbenchLibrary(page);
    await expect(page.getByRole('button', { name: width >= 1024 ? 'Библиотека' : 'Меню', exact: true })).toBeFocused();
    await openWorkbenchLibrary(page);
    expect(state.factReads.workspace).toBe(1);
    await library.getByRole('button', { name: 'Добавить в рабочее место', exact: true }).click();
    await expect.poll(() => state.copies.length).toBe(1);
    expect(state.copies[0].document_path).toBeUndefined();
    await closeWorkbenchLibrary(page);
    await page.getByRole('button', { name: 'IDE', exact: true }).click();
    await expect(page.getByTestId('ide-studio')).toBeVisible();
    await expect(page.getByTestId('chat-backdrop')).toHaveCount(0);
    await expect(page.getByTestId('ide-studio').getByRole('tab', { name: 'Библиотека', exact: true })).toHaveCount(0);
    await expect(page.getByTestId('ide-studio').getByTestId('work-library-nav')).toHaveCount(0);
    expect(state.activations).toBe(0); expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test(`returning Chat to PDF retains the loaded editor without replaying discovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 851 });
    const state = await fixture(page);
    const editor = page.getByRole('textbox', { name: 'Текст блока intro', exact: true });
    await expect(editor).toHaveValue(state.draft.blocks[1].text);
    const node = await editor.elementHandle();
    const reads = { ...state.factReads };
    expect(reads).toEqual({ workspace: 1, project: 1, authoring: 1, profiles: 1 });
    for (let index = 0; index < 3; index += 1) {
      await expect(page.getByTestId('chat-backdrop')).toHaveCount(0);
      await page.getByRole('button', { name: 'Чат', exact: true }).click();
      await expect(page.getByTestId('pdf-studio')).toBeHidden();
      await expect(page.getByTestId('chat-backdrop')).toHaveCount(1);
      await page.getByRole('button', { name: 'PDF', exact: true }).click();
      await expect(page.getByTestId('chat-backdrop')).toHaveCount(0);
      await expect(editor).toBeVisible();
      await expect(editor).toHaveValue(state.draft.blocks[1].text);
      expect(await editor.evaluate((current, previous) => current === previous, node)).toBe(true);
      expect(state.factReads).toEqual(reads);
      await expect(page.getByRole('button', { name: 'Создать рабочее место для PDF', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Создать проект', exact: true })).toHaveCount(0);
    }
    expect(state.activations).toBe(0); expect(state.leaseAcquisitions).toBe(0);
    expect(state.writes).toHaveLength(0); expect(state.builds).toHaveLength(0);
    expect(state.requests).toHaveLength(0);
  });
}

test('PDF completion reloads newly available semantic content without leaving the studio', async ({ page }) => {
  const state = await fixture(page, { semanticAbsent: true });
  await expect(page.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toHaveCount(0);
  await startDocumentRun(page, state);
  state.semanticReady = true;
  state.version = 2; state.revision = 'revision-2';
  state.draft = { ...state.draft, title: 'Обновлённое содержание', blocks: state.draft.blocks.map((block) =>
    block.block_id === 'intro' ? { ...block, text: 'Новый текст из проекта' } : block) };
  state.socket.send(JSON.stringify({ type: 'agent_reply', job_id: 'pdf-job-1', reply: 'Обновлено',
    metadata: { execution_status: 'completed', document_project: PROJECT } }));
  await expect(page.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toHaveValue('Новый текст из проекта');
  await expect(page.getByRole('textbox', { name: 'Название документа', exact: true })).toHaveValue('Обновлённое содержание');
  expect(state.requests).toHaveLength(1);
  expect(state.writes).toHaveLength(0);
  expect(state.builds).toHaveLength(0);
});

test('source-only content replacement explains the loss and does not write before explicit consent', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  const state = await fixture(page, { semanticAbsent: true });
  const start = page.getByRole('button', { name: 'Новое содержание без ИИ', exact: true });
  await start.click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toContainText('Текущие исходники LaTeX будут заменены');
  await expect(dialog.getByRole('button', { name: 'Отмена', exact: true })).toBeFocused();
  expect(state.leaseAcquisitions).toBe(0); expect(state.writes).toHaveLength(0);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden(); await expect(start).toBeFocused();
  await start.click();
  await dialog.getByRole('button', { name: 'Создать новое содержание', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Текст блока intro', exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(1); expect(state.leaseAcquisitions).toBe(1);
  expect(state.builds).toHaveLength(0); expect(state.requests).toHaveLength(0);
});

for (const width of [1920, 1100, 900, 320]) {
  test(`PDF compact controls and long project names fit ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 851 });
    const state = await fixture(page, { presentation: true, title: 'Очень длинное название презентации для проверки компактного выбора проекта и адаптивной панели '.repeat(3) });
    const toolbar = page.getByTestId('pdf-studio-toolbar');
    const project = page.getByTestId('pdf-project-selector');
    const block = page.getByTestId('pdf-block-toolbar');
    await expect(block.getByText('Слайд', { exact: true })).toBeVisible();
    expect((await page.getByTestId('pdf-block-type-selector').boundingBox()).width).toBeLessThanOrEqual(200);
    if (width >= 768) expect((await project.boundingBox()).width).toBeLessThanOrEqual(320);
    const expectedHeight = width < 768 ? 30 : 34;
    const selectorBox = await project.boundingBox();
    const materialsBox = await toolbar.getByRole('button', { name: 'Материалы', exact: true }).boundingBox();
    expect(Math.abs(selectorBox.y - materialsBox.y)).toBeLessThanOrEqual(1);
    expect(selectorBox.height).toBe(expectedHeight);
    for (const name of ['Материалы', 'Оформление', 'Собрать черновик', 'Проверить финал']) {
      expect((await toolbar.getByRole('button', { name, exact: true }).boundingBox()).height).toBe(expectedHeight);
    }
    const control = project.getByRole('combobox');
    await control.focus(); await control.press('ArrowDown');
    await expect(page.getByRole('option').filter({ hasText: state.draft.title })).toBeVisible();
    await control.press('Escape');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `.work/pdf-controls-polished-${width}-${testInfo.project.name}.png`, fullPage: true, scale: 'css' });
    expect(state.requests).toHaveLength(0); expect(state.builds).toHaveLength(0);
  });
}
