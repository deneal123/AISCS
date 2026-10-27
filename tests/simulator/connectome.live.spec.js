const { test, expect } = require('@playwright/test');

test.skip(!process.env.SIMULATION_E2E_STATE || !process.env.SIMULATION_E2E_FULL_CNS,
  'Requires owned, completed MaleCNS records in the running stack');
const scene = page => page.locator('canvas[data-mesh-parts="85"]');
async function open(page, id = process.env.SIMULATION_E2E_FULL_CNS) {
  await page.goto('/simulator?run=' + id);
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '166700', { timeout: 30000 });
  await expect(scene(page)).toHaveAttribute('data-connectome-edges', '25582938');
}
async function seek(page, time) {
  await page.getByLabel('Время воспроизведения', { exact: true }).evaluate((input, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  }, time);
  await expect(scene(page)).toHaveAttribute('data-model-time-ms', time.toFixed(3));
}

test('full graph, calculated propagation, rewind and quiet control', async ({ page }, info) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await open(page);
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  await seek(page, 60);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-connectome-active-nodes'))).toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath('full-cns-active.png') });
  await seek(page, 0); await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  const frame = await scene(page).getAttribute('data-render-count'); await page.waitForTimeout(300);
  await expect(scene(page)).toHaveAttribute('data-render-count', frame);
  if (process.env.SIMULATION_E2E_FULL_CNS_QUIET) {
    await open(page, process.env.SIMULATION_E2E_FULL_CNS_QUIET);
    await seek(page, 60); await expect(scene(page)).toHaveAttribute('data-connectome-active-nodes', '0');
    await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  }
  expect(errors).toEqual([]);
});

test('source mesh selects the head input; electrode mode exits input picking', async ({ page }) => {
  await open(page);
  const bounds = await scene(page).boundingBox(); let selected = false;
  for (const [x, y] of [[.62, .48], [.64, .52], [.66, .50], [.63, .56], [.68, .54], [.60, .5]]) {
    const button = page.getByRole('button', { name: 'Область воздействия', exact: true });
    if (await button.getAttribute('aria-pressed') !== 'true') await button.click();
    await scene(page).click({ position: { x: bounds.width * x, y: bounds.height * y } });
    selected = await page.getByText(/Вход следующего опыта: Голова/).count() > 0;
    if (selected) break;
  }
  expect(selected).toBe(true);
  await page.getByRole('button', { name: 'Область воздействия', exact: true }).click();
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Область воздействия', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await page.keyboard.press('Escape');
});

test('unavailable full-network buffer has read-only recovery without another calculation', async ({ page }) => {
  let unavailable = true, posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await page.route(/\/api\/simulations\/v1\/runs\/[^/]+\/artifacts\//, async route => {
    if (unavailable) await route.fulfill({ status: 503, json: { detail: 'temporary artifact outage' } });
    else await route.continue();
  });
  await page.goto('/simulator?run=' + process.env.SIMULATION_E2E_FULL_CNS);
  await expect(page.getByRole('button', { name: 'Повторить загрузку коннектома', exact: true })).toBeVisible({ timeout: 30000 });
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '0');
  unavailable = false;
  await page.getByRole('button', { name: 'Повторить загрузку коннектома', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '166700');
  expect(posts).toBe(0);
});

test('both full-network scenes restore from the URL with the same clock', async ({ page }, info) => {
  test.skip(!process.env.SIMULATION_E2E_FULL_CNS_MOVED, 'Requires an owned moved-electrode record');
  await page.goto('/simulator?run=' + process.env.SIMULATION_E2E_FULL_CNS_MOVED + '&compare=' + process.env.SIMULATION_E2E_FULL_CNS + '&view=comparison');
  await expect(scene(page)).toHaveCount(2);
  for (const canvas of await scene(page).all()) await expect(canvas).toHaveAttribute('data-connectome-nodes', '166700', { timeout: 30000 });
  await page.getByLabel('Время воспроизведения', { exact: true }).evaluate(input => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '60');
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  for (const canvas of await scene(page).all()) await expect(canvas).toHaveAttribute('data-model-time-ms', '60.000');
  await page.screenshot({ path: info.outputPath('full-cns-pair.png') });
});
