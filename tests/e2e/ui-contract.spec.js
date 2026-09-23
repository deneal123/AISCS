const { test, expect } = require('@playwright/test');
const axeCore = require('axe-core');

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

async function expectNoSevereAxeViolations(page, surface) {
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
  expect(violations, `${surface}: ${JSON.stringify(violations)}`).toEqual([]);
}

test.describe('S27 accessibility contract', () => {
  test.beforeEach(async ({ page }) => installApi(page));

  for (const scenario of [
    { name: 'chat', path: `/chat/${THREAD_ID}`, ready: 'Новый чат' },
    { name: 'work', path: `/chat/${THREAD_ID}?surface=work`, ready: 'Работа' },
    { name: 'admin', path: '/admin', ready: 'Админ-панель' },
    { name: 'not-found', path: '/missing-s27-route', ready: 'Такой страницы нет' },
  ]) {
    test(`${scenario.name} has no serious or critical violations`, async ({ page }) => {
      await page.goto(scenario.path, { waitUntil: 'domcontentloaded' });
      await expect(page.getByText(scenario.ready, { exact: false }).first()).toBeVisible();
      await expectNoSevereAxeViolations(page, scenario.name);
    });
  }

  test('reduced motion and forced colors keep the primary Work action reachable', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' });
    await page.goto(`/chat/${THREAD_ID}?surface=work`, { waitUntil: 'domcontentloaded' });
    const action = page.getByTestId('work-activate');

    await action.focus();
    await expect(action).toBeFocused();
    await expect(action).toBeVisible();
    expect(await page.evaluate(() => ({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      forced: matchMedia('(forced-colors: active)').matches,
    }))).toEqual({ reduced: true, forced: true });
  });
});
