const { test, expect } = require('@playwright/test');

test.skip(!process.env.SIMULATION_E2E_STATE || !process.env.SIMULATION_E2E_RECOGNITION,
  'Requires owned, completed CNS recognition examples');
const runs = process.env.SIMULATION_E2E_RECOGNITION
  ? JSON.parse(process.env.SIMULATION_E2E_RECOGNITION) : {};

async function openRecording(page, id) {
  await page.goto('/simulator?run=' + id);
  await page.getByRole('button', { name: 'Запись', exact: true }).click();
  await expect(page.getByText(/Заданное условие:/)).toBeVisible({ timeout: 30000 });
}

test('saved errors and independent sample sizes remain visible without another calculation', async ({ page }, info) => {
  let posts = 0;
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1;
  });
  await openRecording(page, runs.head);
  await expect(page.getByRole('button', { name: 'Нейроны', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Электроды', exact: true })).toHaveCount(0);
  await expect(page.getByText('Заданное условие: Сильное воздействие. Распознано: Слабое воздействие.', { exact: true })).toBeVisible();
  await expect(page.getByText(/Проверка области «Голова»: 75\.0%/)).toBeVisible();
  await expect(page.getByText(/12 записей из 4 конфигураций/)).toBeVisible();
  await expect(page.getByText(/36 \/ 12 \/ 12 записей/)).toBeVisible();
  await expect(page.getByText(/71\.9% на 96 записях из 32 конфигураций/)).toBeVisible();
  await expect(page.getByText(/61\.5–81\.3%/)).toBeVisible();
  await expect(page.locator('table td[data-error="true"]').first()).toBeVisible();
  await page.screenshot({ path: info.outputPath('recognition-preserved-error.png') });
  await page.reload();
  await expect(page.getByText(/Распознано: Слабое воздействие/)).toBeVisible();
  expect(posts).toBe(0);
  expect(errors).toEqual([]);
});

test('outside the checked domain has a reason and no invented accuracy', async ({ page }, info) => {
  await openRecording(page, runs.outside);
  await expect(page.getByText(/предсказание недоступно/)).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: /проверенн/ })).toBeVisible();
  await expect(page.getByText(/сбалансированной точности/)).toHaveCount(0);
  await expect(page.locator('table')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('recognition-outside-domain.png') });
});
