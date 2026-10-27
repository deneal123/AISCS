const { test, expect } = require('@playwright/test');
test.use({ serviceWorkers: 'block' });
const PRIVATE = 'PRIVATE_RESPONSE_BODY';

async function expectMobileFieldSizing(page, fields) {
  if (!await page.evaluate(() => matchMedia('(max-width: 767px), (hover: none) and (pointer: coarse)').matches)) return;
  for (const field of fields) {
    expect(await field.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

async function fixture(page, code, otp = false) {
  let logins = 0;
  let verifies = 0;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/v1/login') {
      logins += 1;
      await route.fulfill(otp ? { json: { status: 'email_sent' } }
        : { status: 503, json: { code, detail: PRIVATE } });
    } else if (path === '/api/auth/v1/verify') {
      verifies += 1;
      await route.fulfill({ status: 400, json: { code: 'invalid_code', detail: PRIVATE } });
    } else if (path === '/api/profile/me' || path === '/api/auth/v1/refresh') {
      await route.fulfill({ status: 401, json: { code: 'unauthorized' } });
    } else await route.fulfill({ json: {} });
  });
  await page.goto('/login');
  await page.locator('input[type="email"]').fill('synthetic@example.test');
  // Isolated fixture credentials, never a real account or deployment secret.
  await page.locator('input[type="password"]').fill('Synthetic123');
  await page.getByRole('button', { name: /^Войти$/ }).click();
  return () => ({ logins, verifies });
}

for (const code of ['constructor', '__proto__']) {
  test(`unknown HTTP code ${code} keeps login fields and renders safe feedback`, async ({ page }) => {
    const counts = await fixture(page, code);
    await expect(page.getByText('Сервис временно недоступен. Попробуйте позже.', { exact: true })).toBeVisible();
    await expect(page.locator('input[type="email"]')).toHaveValue('synthetic@example.test');
    await expect(page.locator('input[type="password"]')).toHaveValue('Synthetic123');
    await expectMobileFieldSizing(page, [page.locator('input[type="email"]'), page.locator('input[type="password"]')]);
    await expect(page.locator('body')).not.toContainText(PRIVATE);
    await expect(page.getByRole('heading', { name: 'Не удалось открыть страницу' })).toHaveCount(0);
    expect(counts().logins).toBe(1);
  });
}

test('OTP feedback retains its known code through HTTP and form normalization', async ({ page }) => {
  const counts = await fixture(page, '', true);
  for (let index = 0; index < 6; index += 1) {
    const digit = page.getByLabel(`Код из письма: цифра ${index + 1} из 6`, { exact: true });
    await expectMobileFieldSizing(page, [digit]);
    await digit.fill(String(index + 1));
  }
  await expect(page.getByText('Неверный код. Проверьте цифры из письма и попробуйте снова.', { exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText(PRIVATE);
  expect(counts()).toEqual({ logins: 1, verifies: 1 });
});
