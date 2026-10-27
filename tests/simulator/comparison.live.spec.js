const { test, expect } = require('@playwright/test');
const fs = require('fs');

const fixtures = process.env.SIMULATION_E2E_FIXTURES
  ? JSON.parse(fs.readFileSync(process.env.SIMULATION_E2E_FIXTURES, 'utf8')) : null;
test.skip(!process.env.SIMULATION_E2E_STATE || !fixtures, 'Requires owned saved comparison records');

async function time(page, value) {
  await page.getByLabel('Время воспроизведения', { exact: true }).evaluate((input, next) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(next));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

async function selectSaved(page, id) {
  const record = page.locator(`[data-run-id="${id}"]`);
  while (!await record.count()) {
    const count = await page.locator('[data-run-id]').count();
    await page.getByRole('button', { name: 'Ещё опыты', exact: true }).click();
    await expect.poll(() => page.locator('[data-run-id]').count()).toBeGreaterThan(count);
  }
  await record.click();
}

test('shared camera, clock and signal scale compare stimulus, adaptation and electrode records', async ({ page }, testInfo) => {
  const errors = [];
  let calculations = 0;
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/api/simulations/v1/runs')) calculations += 1; });
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && /THREE|shader/i.test(message.text())) errors.push(message.text()); });
  const runs = fixtures.runs;
  await page.goto('/simulator?run=' + runs.none.id);
  await expect(page.getByLabel('Трёхмерная сцена мухи и локальной модели', { exact: true }))
    .toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await page.getByRole('button', { name: 'Сравнить', exact: true }).click();
  await selectSaved(page, runs.strong.id);
  const a = page.getByLabel('Синхронная сцена A', { exact: true });
  const b = page.getByLabel('Синхронная сцена B', { exact: true });
  await expect(a).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(b).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await time(page, 75);
  await expect(a).toHaveAttribute('data-model-time-ms', '75.000');
  await expect(b).toHaveAttribute('data-model-time-ms', '75.000');
  const plot = page.getByRole('img', { name: 'Общая временная шкала: синаптический вход, спайки, условное движение лапок и запись E1 относительно REF', exact: true });
  await expect(plot).toHaveAttribute('data-model-time-ms', '75.000');
  await expect(plot).toHaveAttribute('data-reference-run', runs.none.id);
  const expectedRange = Math.max(.1, runs.none.peak_signal_uv, runs.strong.peak_signal_uv);
  expect(Number(await plot.getAttribute('data-signal-half-range-uv'))).toBeCloseTo(expectedRange, 7);
  const before = await a.getAttribute('data-camera-pose');
  const bounds = await a.boundingBox();
  await page.mouse.move(bounds.x + bounds.width * .7, bounds.y + bounds.height * .5);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * .7 + 60, bounds.y + bounds.height * .5 - 25, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => a.getAttribute('data-camera-pose')).not.toBe(before);
  await expect.poll(async () => await a.getAttribute('data-camera-pose') === await b.getAttribute('data-camera-pose')).toBe(true);
  const keyboardPose = await a.getAttribute('data-camera-pose');
  await a.focus(); await a.press('Shift+ArrowLeft');
  await expect.poll(() => a.getAttribute('data-camera-pose')).not.toBe(keyboardPose);
  await expect.poll(async () => await a.getAttribute('data-camera-pose') === await b.getAttribute('data-camera-pose')).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('comparison-stimulus.png') });
  await selectSaved(page, runs.weak.id);
  await expect(b).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await time(page, 75);
  await expect(plot).toHaveAttribute('data-reference-run', runs.none.id);
  await page.screenshot({ path: testInfo.outputPath('comparison-weak.png') });
  await selectSaved(page, runs.strong.id);
  await expect(b).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });

  await page.getByRole('button', { name: 'Убрать сравнение', exact: true }).click();
  await page.getByRole('button', { name: 'Сравнить', exact: true }).click();
  await selectSaved(page, runs.adaptation.id);
  await expect(b).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await time(page, 75);
  await expect(plot).toHaveAttribute('data-reference-run', runs.strong.id);
  await expect(a).toHaveAttribute('data-model-time-ms', '75.000');
  await expect(b).toHaveAttribute('data-model-time-ms', '75.000');
  await page.screenshot({ path: testInfo.outputPath('comparison-adaptation.png') });

  await selectSaved(page, runs.electrode.id);
  await expect(b).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await time(page, 75);
  expect(fixtures.same_currents_electrode_pair).toBe(true);
  expect(runs.strong.cache.data_sha256).toBe(runs.electrode.cache.data_sha256);
  await expect(plot).toHaveAttribute('data-reference-run', runs.strong.id);
  await page.screenshot({ path: testInfo.outputPath('comparison-electrode.png') });
  const radius = Number(await a.getAttribute('data-local-window-radius-px'));
  await page.getByRole('button', { name: 'Приблизить локальную цепь', exact: true }).click();
  await expect.poll(async () => Number(await a.getAttribute('data-local-window-radius-px'))).toBeGreaterThan(radius);
  await expect.poll(async () => await a.getAttribute('data-camera-pose') === await b.getAttribute('data-camera-pose')).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('comparison-local-circuit.png') });
  await page.reload();
  await expect(a).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(b).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(plot).toHaveAttribute('data-reference-run', runs.strong.id);
  await expect(a).toHaveAttribute('data-model-time-ms', '0.000');
  expect(calculations).toBe(0);
  await selectSaved(page, runs.incompatible.id);
  await expect(page.getByText('Для наложения записей выберите одинаковые модель, длительность и шаг расчёта.', { exact: true })).toBeVisible();
  await expect(plot).toHaveAttribute('data-reference-run', '');
  await expect(a).toHaveCount(0);
  await expect(b).toHaveCount(0);
  await page.goto('/simulator?run=' + runs.electrode.id + '&compare=00000000-0000-0000-0000-000000000000&view=comparison');
  await expect(page.getByLabel('Трёхмерная сцена мухи и локальной модели', { exact: true })).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(page.getByText('Закреплённая запись A недоступна. Опыт B открыт без сравнения.', { exact: true })).toBeVisible();
  await expect(a).toHaveCount(0);
  await page.getByRole('button', { name: 'Новый опыт', exact: true }).click();
  await expect(page.getByLabel('Трёхмерная сцена мухи и локальной модели', { exact: true })).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(a).toHaveCount(0);
  await expect(b).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Сравнение', exact: true })).toBeDisabled();
  expect(errors).toEqual([]);
});
