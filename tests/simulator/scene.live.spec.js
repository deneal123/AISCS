const { test, expect } = require('@playwright/test');

test.skip(!process.env.SIMULATION_E2E_STATE || !process.env.SIMULATION_E2E_RUN,
  'Requires an authenticated disposable user and its completed strong-stimulus run');

test('FlyBody, replay, source picking and invalid contact recovery', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && /THREE|shader/i.test(message.text())) errors.push(message.text());
  });
  await page.goto('/simulator?run=' + process.env.SIMULATION_E2E_RUN);
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  const scene = page.getByLabel('Трёхмерная сцена мухи и локальной модели', { exact: true });
  await expect(scene).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(scene).toHaveAttribute('data-leg-roots', '6');
  await expect(scene).toHaveAttribute('data-surface-style', 'flybody-source-normals-v1');
  await expect(scene).toHaveAttribute('data-local-window', 'open');
  // Reduced-motion preference prevents automatic motion. Playback is explicit.
  await expect(page.getByRole('button', { name: 'Воспроизвести запись', exact: true })).toBeVisible();
  await expect(scene).toHaveAttribute('data-reaction-angle-rad', '0.00000');
  await page.waitForTimeout(300);
  const pausedFrames = await scene.getAttribute('data-render-count');
  await page.waitForTimeout(250);
  await expect(scene).toHaveAttribute('data-render-count', pausedFrames);
  await page.screenshot({ path: testInfo.outputPath('flybody-window.png') });
  await page.getByRole('button', { name: 'Окно локальной цепи', exact: true }).click();
  await expect(scene).toHaveAttribute('data-local-window', 'closed');
  await page.screenshot({ path: testInfo.outputPath('flybody-rest.png') });
  await page.getByRole('button', { name: 'Окно локальной цепи', exact: true }).click();
  await expect(scene).toHaveAttribute('data-local-window', 'open');
  await page.getByRole('button', { name: 'Воспроизвести запись', exact: true }).click();
  await expect.poll(async () => Number(await scene.getAttribute('data-reaction-angle-rad'))).toBeGreaterThan(.03);
  await page.getByRole('button', { name: 'Пауза записи', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('flybody-reaction.png') });
  await page.getByRole('button', { name: 'Тело', exact: true }).click();
  await expect(page.getByLabel('Прозрачность тела', { exact: true })).toHaveValue('0.24');
  await page.waitForTimeout(100);
  await page.screenshot({ path: testInfo.outputPath('flybody-xray.png') });
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Запустить', exact: true })).toBeDisabled();
  const bounds = await scene.boundingBox();
  const timings = [];
  let unsupported = null;
  for (const [x, y] of [[.25,.35],[.4,.35],[.55,.35],[.65,.35],[.25,.5],[.4,.5],[.55,.5],[.65,.5],[.25,.65],[.4,.65],[.55,.65],[.65,.65]]) {
    await page.mouse.move(bounds.x + bounds.width * x, bounds.y + bounds.height * y);
    await page.waitForTimeout(50);
    const elapsed = Number(await scene.getAttribute('data-last-pick-ms'));
    if (Number.isFinite(elapsed)) timings.push(elapsed);
    if (await page.locator('[data-region-preview="view-only"]').count()) { unsupported = [x, y]; break; }
  }
  expect(unsupported).not.toBeNull();
  await page.mouse.click(bounds.x + bounds.width * unsupported[0], bounds.y + bounds.height * unsupported[1]);
  await expect(page.getByText('Для этой области ещё нет зарегистрированной модели. Выберите грудную область.', { exact: true })).toBeVisible();
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(page.locator('[data-region-preview="registered"]')).toBeVisible();
  await testInfo.attach('source-picking-timings', { body: JSON.stringify({ unit: 'ms', samples: timings, scope: 'Actual source mesh raycasting; a few UI samples, not a latency guarantee.' }), contentType: 'application/json' });
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(page.getByText('Выбрана локальная грудная область. Контакт задаётся в координатах модели.', { exact: true })).toBeVisible();
  for (const [axis, value] of [['X', '-85'], ['Y', '-35'], ['Z', '0']]) {
    await page.getByLabel(axis + ', мкм', { exact: true }).fill(value);
  }
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toBeDisabled();
  await expect(page.getByRole('alert').filter({ hasText: 'пересекает нейронный источник' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Применить', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Запустить', exact: true })).toBeEnabled();
  await page.reload();
  await expect(scene).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(page.getByRole('button', { name: 'Воспроизвести запись', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Параметры модели', exact: true }).click();
  await page.getByRole('button', { name: 'Слабое', exact: true }).click();
  await expect(page.getByText('Черновик параметров · запись сохранённого опыта', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  expect(errors).toEqual([]);
});

test('source anchor and FlyBody hashes survive a real queued calculation and reload', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'laptop', 'One real calculation is sufficient for this contract');
  const eventFrames = [];
  page.on('websocket', socket => {
    if (!socket.url().includes('/api/simulations/v1/runs/')) return;
    socket.on('framereceived', ({ payload }) => {
      try { eventFrames.push(JSON.parse(String(payload))); } catch { /* Ignore transport pings. */ }
    });
  });
  await page.goto('/simulator?run=' + process.env.SIMULATION_E2E_RUN);
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  const scene = page.getByLabel('Трёхмерная сцена мухи и локальной модели', { exact: true });
  await expect(scene).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  const bounds = await scene.boundingBox();
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(page.getByText('Выбрана локальная грудная область. Контакт задаётся в координатах модели.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  const created = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/simulations/v1/runs'));
  await page.getByRole('button', { name: 'Запустить', exact: true }).click();
  const response = await created;
  expect(response.ok()).toBe(true);
  const run = await response.json();
  const registration = run.configuration.placement.registration;
  expect(registration.mesh_asset_id).toBe('flybody-sim003-fdbbd866-rest-v1');
  expect(registration.surface_anchor.mesh_part).toBe('thorax');
  expect(registration.surface_anchor.triangle).toBeLessThan(registration.mesh_triangle_count);
  const endpoint = response.url() + '/' + run.id;
  let complete;
  await expect.poll(async () => {
    complete = await (await page.request.get(endpoint)).json();
    return complete.state;
  }, { timeout: 45000 }).toBe('completed');
  await expect.poll(() => eventFrames.some(frame => frame.type === 'snapshot' && frame.run?.id === run.id)).toBe(true);
  const manifest = await (await page.request.get(endpoint + '/manifest')).json();
  expect(manifest.configuration_sha256).toBe(run.configuration_sha256);
  expect(manifest.registration.registration).toEqual(registration);
  expect(manifest.files).toHaveLength(10);
  const preview = complete.result.preview;
  expect(preview.input_events.length).toBeGreaterThan(0);
  expect(preview.input_events[0].weight_us).toBeGreaterThan(0);
  await page.reload();
  await expect(scene).toHaveAttribute('data-mesh-parts', '85', { timeout: 30000 });
  await expect(page.getByRole('button', { name: 'Воспроизвести запись', exact: true })).toBeVisible();
  const timeline = page.getByRole('img', { name: 'Общая временная шкала: синаптический вход, спайки, условное движение лапок и запись E1 относительно REF', exact: true });
  await expect(timeline).toHaveAttribute('data-input-journal', 'recorded');
  const inputTime = preview.input_events[0].time_ms + .5;
  await page.getByLabel('Время воспроизведения', { exact: true }).evaluate((input, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, inputTime);
  await expect.poll(async () => Number(await scene.getAttribute('data-model-time-ms'))).toBeCloseTo(inputTime, 1);
  await expect(timeline).toHaveAttribute('data-model-time-ms', await scene.getAttribute('data-model-time-ms'));
  await expect(scene).toHaveAttribute('data-active-input-cells', /0/);
  await page.screenshot({ path: testInfo.outputPath('source-input-response.png') });
  await testInfo.attach('published-registration', { body: JSON.stringify({ run_id: run.id, registration, configuration_sha256: manifest.configuration_sha256 }, null, 2), contentType: 'application/json' });
});
