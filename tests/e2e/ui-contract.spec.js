const { test, expect } = require('@playwright/test');
const axeCore = require('axe-core');
const fs = require('fs/promises');
const path = require('path');

const THREAD_ID = 's27-a11y-thread';

async function installApi(page) {
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', 's27-opaque-token');
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/profile/me') {
      await route.fulfill({
        json: {
          id: 'user-opaque',
          email: 'ui-contract@example.test',
          permissions: ['admin'],
        },
      });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/work`) {
      await route.fulfill({
        json: {
          contract_version: 2,
          workspace: {
            state: 'absent', revision: '', recovered: false, entries: [], history: [],
          },
          room: {
            state: 'absent', issues: [], leases: [], activity: [], control: { state: 'running' },
          },
          library: { state: 'ready', items: [], next_cursor: null, next_offset: null },
        },
      });
      return;
    }
    if (path === `/api/chats/${THREAD_ID}/ide/repositories`) {
      await route.fulfill({ json: { items: [], next_offset: null } });
      return;
    }
    if (path.includes(`/api/chats/${THREAD_ID}/ide/`)) {
      const id = '20000000-0000-0000-0000-000000000001';
      const runtime = { repository_id: id, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } };
      const json = path.endsWith('/clone-attempt') ? { attempt: null }
        : path.endsWith('/prepare') ? { repository: { repository_id: id, name: 'IDE fixture', state: 'registered' }, runtime, git: { initialized: true, branch: 'main' } }
        : path.endsWith('/runtime') ? runtime : path.endsWith('/git') ? { repository_id: id, generation: 'a'.repeat(64), initialized: true, branch: 'main' }
          : { repository_id: id, generation: 'a'.repeat(64), entries: [], truncated: false };
      await route.fulfill({ json }); return;
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
      await route.fulfill({ json: { chats: [{ thread_id: THREAD_ID, title: 'UI contract' }] } });
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
    if (path === '/api/admin/analytics') {
      await route.fulfill({ json: {} });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function expectNoSevereAxeViolations(page, surface, testInfo) {
  await page.addScriptTag({ content: axeCore.source });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
      resultTypes: ['violations'],
    });
    return result.violations
      .filter((item) => ['serious', 'critical'].includes(item.impact))
      .map((item) => ({
        id: item.id,
        impact: item.impact,
        nodes: item.nodes.map((node) => ({
          target: node.target,
          summary: node.failureSummary,
        })),
      }));
  });
  // Keep the portable acceptance artifact bounded: no DOM HTML, field values
  // or user text. The normal assertion still retains the full severity gate.
  const findingsPath = testInfo.outputPath('bounded-axe-findings.json');
  await fs.mkdir(path.dirname(findingsPath), { recursive: true });
  await fs.writeFile(findingsPath, JSON.stringify(violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      count: item.nodes.length,
    }))));
  await testInfo.attach('bounded-axe-findings', {
    path: findingsPath,
    contentType: 'application/json',
  });
  expect(violations, `${surface}: ${JSON.stringify(violations)}`).toEqual([]);
}

test.describe('S27 accessibility contract', () => {
  test('admin navigation stays visible and keyboard reachable on a narrow screen', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 393, height: 851 });
    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    const navigation = page.getByRole('tablist', { name: 'Разделы админки' });
    await expect(navigation).toBeVisible();
    const labels = ['Аналитика', 'Настройки', 'Тарифы и цены', 'Пользователи'];
    const assertGeometry = async () => {
      for (const label of labels) {
        const tab = navigation.getByRole('tab', { name: label, exact: true });
        await expect(tab).toBeVisible();
        // A preceding trial click can scroll a zoomed WebKit page. Compare
        // current rectangles, not a parent position captured before that scroll.
        const outer = await navigation.boundingBox();
        const box = await tab.boundingBox();
        expect(box.x).toBeGreaterThanOrEqual(outer.x - 1);
        expect(box.x + box.width).toBeLessThanOrEqual(outer.x + outer.width + 1);
        expect(box.y + box.height).toBeLessThanOrEqual(outer.y + outer.height + 1);
        await tab.click({ trial: true });
      }
    };
    await assertGeometry();
    await navigation.getByRole('tab', { name: 'Аналитика', exact: true }).focus();
    await page.keyboard.press('End');
    await expect(navigation.getByRole('tab', { name: 'Пользователи', exact: true })).toBeFocused();
    await expect(navigation.getByRole('tab', { name: 'Пользователи', exact: true })).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('Home');
    await expect(navigation.getByRole('tab', { name: 'Аналитика', exact: true })).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath('admin-navigation.png') });
    // CSS zoom tests magnified reflow; it is not a claim about OS/browser zoom.
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; });
    await assertGeometry();
    await expectNoSevereAxeViolations(page, 'admin-navigation-magnified', testInfo);
  });

  test.beforeEach(async ({ page }) => installApi(page));

  test('admin refresh preserves a sibling draft and retry does not repeat save', async ({ page }, testInfo) => {
    await page.setViewportSize(testInfo.project.name === 'mobile-chrome'
      ? { width: 393, height: 851 } : { width: 1440, height: 900 });
    const settings = [
      { key: 'first', label: 'Сохраняемая настройка', group: 'Проверка', type: 'str', value: 'one', default: 'default', overridden: true },
      { key: 'second', label: 'Несохранённая настройка', group: 'Проверка', type: 'str', value: 'two', default: 'two', overridden: false },
    ];
    let reads = 0;
    let saves = 0;
    let recovered = false;
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await page.route('**/api/admin/settings**', async (route) => {
      if (route.request().method().toUpperCase() === 'GET') {
        reads += 1;
        if (saves > 0 && !recovered) {
          await held;
          await route.fulfill({ status: 503, json: { detail: 'private-refresh-marker' } });
        } else {
          await route.fulfill({ json: { settings } });
        }
      } else {
        saves += 1;
        settings[0].value = route.request().postDataJSON().value;
        await route.fulfill({ json: { status: 'ok', value: settings[0].value } });
      }
    });
    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    await page.getByRole('tab', { name: 'Настройки', exact: true }).click();
    const first = page.getByRole('textbox', { name: settings[0].label, exact: true });
    const second = page.getByRole('textbox', { name: settings[1].label, exact: true });
    await first.fill('acknowledged change');
    await second.fill('local draft');
    await second.evaluate((element) => { element.dataset.continuityProbe = 'mounted'; });
    const initialReads = reads;
    await page.getByRole('button', { name: 'Сохранить', exact: true }).first().click();
    await expect.poll(() => reads).toBe(initialReads + 1);
    await expect(second).toHaveValue('local draft');
    await expect(second).toHaveAttribute('data-continuity-probe', 'mounted');
    await second.focus();
    await expect(second).toBeFocused();
    release();
    await expect(page.getByText('Не удалось обновить настройки. Показаны последние доступные значения.')).toBeVisible();
    await expect(second).toHaveValue('local draft');
    await expect(page.locator('body')).not.toContainText('private-refresh-marker');
    const failedReads = reads;
    recovered = true;
    await page.getByRole('button', { name: /Повторить/ }).click();
    await expect.poll(() => reads).toBe(failedReads + 1);
    await expect(second).toHaveValue('local draft');
    await expect(second).toHaveAttribute('data-continuity-probe', 'mounted');
    expect(saves).toBe(1);
    await expectNoSevereAxeViolations(page, 'admin-refresh-continuity', testInfo);
    await page.screenshot({ path: testInfo.outputPath('admin-refresh.png') });
  });

  for (const scenario of [
    { name: 'chat', path: `/chat/${THREAD_ID}`, ready: 'Новый чат' },
    { name: 'ide', path: `/chat/${THREAD_ID}?surface=work`, ready: 'Среда доступна' },
    { name: 'admin', path: '/admin', ready: 'Админ-панель' },
    { name: 'not-found', path: '/missing-s27-route', ready: 'Такой страницы нет' },
  ]) {
    test(`${scenario.name} has no serious or critical violations`, async ({ page }, testInfo) => {
      await page.goto(scenario.path, { waitUntil: 'domcontentloaded' });
      if (scenario.name === 'chat') {
        // The sidebar's New chat action is intentionally hidden on narrow
        // screens. Readiness belongs to the active surface, not that drawer.
        await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
      } else {
        await expect(page.getByText(scenario.ready, { exact: false }).first()).toBeVisible();
      }
      if (scenario.name === 'admin') {
        const panel = page.getByTestId('admin-active-panel');
        await expect(panel).toBeVisible();
        expect(await panel.evaluate((element) => ({
          revealed: Boolean(element.closest('.in-view-reveal')),
          opacity: getComputedStyle(element).opacity,
        }))).toEqual({ revealed: false, opacity: '1' });
      }
      await expectNoSevereAxeViolations(page, scenario.name, testInfo);
      if (scenario.name === 'admin') {
        await page.screenshot({ path: testInfo.outputPath('admin-opacity.png') });
      }
    });
  }

  test('reduced motion and forced colors keep the IDE read action reachable', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    const action = page.getByRole('button', { name: 'Обновить IDE', exact: true });

    await expect(page.getByText('Среда доступна', { exact: true })).toBeVisible();
    await expect(action).toBeEnabled();
    await action.focus();
    await expect(action).toBeFocused();
    await expect(action).toBeVisible();
    expect(await page.evaluate(() => ({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      forced: matchMedia('(forced-colors: active)').matches,
    }))).toEqual({ reduced: true, forced: true });
  });

  test('admin setting failures retain input and hide raw integration bodies', async ({ page }, testInfo) => {
    const marker = 'private-admin-setting-response-marker';
    const setting = { key: 'fixture_setting', label: 'Эталонная настройка',
      group: 'Проверка', type: 'str', value: 'initial', overridden: true };
    let saves = 0;
    let resets = 0;
    let reads = 0;
    let pageErrors = 0;
    page.on('pageerror', () => { pageErrors += 1; });
    await page.route('**/api/admin/settings**', async (route) => {
      if (route.request().method().toUpperCase() === 'GET') {
        reads += 1;
        await route.fulfill({ json: { settings: [setting] } });
      } else if (++saves === 1) {
        await route.fulfill({ status: 503, json: { detail: marker } });
      } else {
        setting.value = route.request().postDataJSON().value;
        await route.fulfill({ json: {} });
      }
    });
    await page.route('**/api/admin/settings/fixture_setting', async (route) => {
      resets += 1;
      await route.fulfill({ status: 503, json: { detail: { message: marker } } });
    });
    await page.goto('/admin', { waitUntil: 'domcontentloaded' });
    await page.getByRole('tab', { name: 'Настройки', exact: true }).click();
    await expect.poll(() => reads).toBeGreaterThan(0);
    const input = page.getByRole('textbox', { name: setting.label, exact: true });
    await input.fill('retained local edit');
    const save = page.getByRole('button', { name: 'Сохранить', exact: true });
    await save.click();
    await expect(page.getByRole('alert')).toHaveText('Сервис временно недоступен. Попробуйте позже.');
    await expect(input).toHaveValue('retained local edit');
    await expect(page.locator('body')).not.toContainText(marker);
    await page.getByRole('button', { name: 'Сбросить', exact: true }).click();
    await expect.poll(() => resets).toBe(1);
    await expect(page.getByRole('alert')).toHaveText('Сервис временно недоступен. Попробуйте позже.');
    await expect(input).toHaveValue('retained local edit');
    await expect(page.locator('body')).not.toContainText(marker);
    await expectNoSevereAxeViolations(page, 'admin-setting-error', testInfo);
    await save.focus();
    await save.press('Enter');
    await expect.poll(() => saves).toBe(2);
    await expect(input).toHaveValue('retained local edit');
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(pageErrors).toBe(0);
  });
});
