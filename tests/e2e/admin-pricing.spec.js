const { test, expect } = require('@playwright/test');

const ADMIN_PROFILE = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'admin@example.test',
  permissions: ['admin'],
};

const PRICING = {
  pricing: [
    {
      provider: 'openrouter',
      model_id: 'shared/model',
      priced: true,
      price_in_rub_per_1k: 0.1,
      price_out_rub_per_1k: 0.2,
    },
    {
      provider: 'routerai',
      model_id: 'shared/model',
      priced: true,
      price_in_rub_per_1k: 0.3,
      price_out_rub_per_1k: 0.4,
    },
  ],
  pricing_sync: {
    providers: [
      {
        provider: 'openrouter',
        level: 'warning',
        freshness_seconds: 90000,
        synced_models: 378,
        next_action: 'Запланируйте обновление каталога.',
      },
    ],
  },
};

const RECONCILE = {
  healthy: true,
  actual_margin: 2.5,
  status: { level: 'warning', next_action: 'Проверьте fallback-цены.' },
  cost_guard: {
    raw_cost_rub: 42.5,
    fallback_pricing: 1,
    prompt_budget_stops: 2,
    active_reservations: 3,
    expired_reservations: 0,
  },
};

const HEALTH = {
  active_provider: 'routerai',
  status: {
    level: 'warning',
    next_action: 'provider-health-needs-operator-action-because-the-last-probe-is-unavailable',
  },
  providers: {
    routerai: {
      configured: true,
      reachable: false,
      disabled: false,
      status: 'warning',
      reason: 'provider-health-needs-operator-action-because-the-last-probe-is-unavailable',
    },
  },
};

async function mockAdminApi(page, { reconcileUnavailable = false } = {}) {
  const requests = [];
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    requests.push(pathname);
    if (pathname === '/api/profile/me') {
      await route.fulfill({ json: ADMIN_PROFILE });
    } else if (pathname === '/api/admin/billing/pricing') {
      await route.fulfill({ json: PRICING });
    } else if (pathname === '/api/admin/billing/reconcile') {
      await route.fulfill(reconcileUnavailable ? { status: 503, json: { detail: 'unavailable' } } : { json: RECONCILE });
    } else if (pathname === '/api/admin/providers/health') {
      await route.fulfill({ json: HEALTH });
    } else {
      // Other admin widgets may mount alongside PricingPanel. A successful empty
      // response keeps this scenario focused on the protected pricing surface.
      await route.fulfill({ json: {} });
    }
  });
  return requests;
}

test.describe('admin pricing on mobile', () => {
  test('shows pricing freshness and cost guard without horizontal overflow', async ({ page, isMobile, browserName }) => {
    // This fixture replaces a cross-origin protected API with route fulfils.
    // Playwright WebKit does not dispatch the PricingPanel effect in that
    // synthetic setup; the real WebKit mobile surface remains covered by the
    // responsive suite. Keep this provider-aware contract on mobile Chromium.
    test.skip(!isMobile || browserName !== 'chromium', 'Provider-aware mock contract runs on mobile Chromium.');
    const requests = await mockAdminApi(page);
    // The production host rewrites /admin to index.html. Set the route before
    // React starts so the static shell used in local E2E has identical routing
    // semantics in every browser engine.
    await page.addInitScript(() => {
      window.history.replaceState({}, '', '/admin');
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: 'Админ-панель' })).toBeVisible();
    const pricingTab = page.getByRole('tab', { name: 'Тарифы и цены' });
    await pricingTab.focus();
    await pricingTab.press('Enter');

    await expect.poll(() => requests).toContain('/api/admin/billing/pricing');

    const freshness = page.getByRole('region', { name: 'Статус свежести тарифов' });
    await expect(freshness).toContainText('openrouter');
    await expect(freshness).toContainText('378 моделей');
    await expect(page.getByText(/fallback 1.*budget-stop 2.*резервов 3\/0/)).toBeVisible();

    await page.setViewportSize({ width: 320, height: 700 });
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  });

  test('wraps degraded provider health details without mobile overflow', async ({ page, isMobile, browserName }) => {
    test.skip(!isMobile || browserName !== 'chromium', 'Provider-aware mock contract runs on mobile Chromium.');
    await mockAdminApi(page);
    await page.setViewportSize({ width: 320, height: 700 });
    await page.addInitScript(() => {
      window.history.replaceState({}, '', '/admin');
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('Статус провайдеров')).toBeVisible();
    await expect(page.getByText(/provider-health-needs-operator-action/).first()).toBeVisible();
    const providerToggle = page.getByRole('checkbox', { name: 'Выключить провайдера routerai' });
    await expect(providerToggle).toBeVisible();
    // Chakra keeps the native input visually hidden; the parent label is the
    // real click/tap surface styled by Checkbox props.
    const toggleBox = await providerToggle.locator('xpath=..').boundingBox();
    expect(toggleBox.width).toBeGreaterThanOrEqual(44);
    expect(toggleBox.height).toBeGreaterThanOrEqual(44);
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  });

  test('keeps prices actionable when reconciliation is unavailable', async ({ page, isMobile, browserName }) => {
    test.skip(!isMobile || browserName !== 'chromium', 'Provider-aware mock contract runs on mobile Chromium.');
    await mockAdminApi(page, { reconcileUnavailable: true });
    await page.setViewportSize({ width: 320, height: 700 });
    await page.addInitScript(() => {
      window.history.replaceState({}, '', '/admin');
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('tab', { name: 'Тарифы и цены' }).press('Enter');

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('Не удалось загрузить сверку себестоимости');
    await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Изменить' }).first()).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  });
});
