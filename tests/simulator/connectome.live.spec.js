const { test, expect } = require('@playwright/test');

test.skip(!process.env.SIMULATION_E2E_STATE || !process.env.SIMULATION_E2E_FULL_CNS,
  'Requires owned, completed MaleCNS records in the running stack');
const scene = page => page.locator('canvas[data-mesh-parts="85"]');
async function open(page, id = process.env.SIMULATION_E2E_FULL_CNS) {
  await page.goto('/simulator?run=' + id, { waitUntil: 'domcontentloaded' });
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '166700', { timeout: 30000 });
  await expect(scene(page)).toHaveAttribute('data-connectome-edges', '25582938');
  await expect(scene(page)).toHaveAttribute('data-connectome-routing', 'body-corridors-v1');
  await expect(scene(page)).toHaveAttribute('data-connectome-morphology-nodes', '26062');
  await expect(scene(page)).toHaveAttribute('data-connectome-visible-nodes', '166700');
  await expect(scene(page)).toHaveAttribute('data-local-model-visible', 'false');
}
async function seek(page, time) {
  await page.getByLabel('Время воспроизведения', { exact: true }).evaluate((input, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(value));
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  }, time);
  await expect(scene(page)).toHaveAttribute('data-model-time-ms', time.toFixed(3));
}

test('a weak saved signal is visible on its actual scientific scale', async ({ page }, info) => {
  const id = process.env.SIMULATION_E2E_FULL_CNS;
  await page.route(`**/api/simulations/v1/runs/${id}`, async route => {
    const response = await route.fetch();
    const run = await response.json();
    run.result.preview.signal_uv = run.result.preview.signal_uv.map((_, index) =>
      index % 400 === 200 ? 4.27e-7 : index % 400 === 201 ? -4.27e-7 : 0);
    await route.fulfill({ response, json: run });
  });
  await open(page, id);
  const plot = page.getByRole('img', { name: 'Запись разности потенциалов E1 относительно REF, микровольты' }).last();
  await expect(plot).toHaveAttribute('data-signal-half-range-uv', '4.27000000e-7');
  await page.screenshot({ path: info.outputPath('weak-signal.png') });
});

test('a linked one-cell trace is labelled and shown separately from the network recording', async ({ page }, info) => {
  const id = process.env.SIMULATION_E2E_FULL_CNS, replayId = '00000000-0000-4000-8000-000000000042';
  await page.route(`**/api/simulations/v1/runs/${id}/replays`, route => route.fulfill({ json: {
    items: [{ id: replayId, state: 'completed' }], next_offset: null,
  } }));
  await page.route(`**/api/simulations/v1/runs/${replayId}`, route => route.fulfill({ json: {
    id: replayId, state: 'completed', configuration: { simulation: {
      electrode_um: [2414.208, 475.136, 593.408], reference_um: [2914.208, 475.136, 593.408],
    } }, result: { preview: {
      body_id: '42', time_ms: [0, 1, 2, 3, 4], signal_uv: [0, 1e-7, -4.27e-7, 1e-7, 0],
    } },
  } }));
  await open(page, id);
  await page.getByRole('button', { name: 'Запись', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Дополнительная запись нейрона' });
  await expect(panel).toContainText('Дополнительная запись нейрона 42');
  await expect(panel).toContainText('это не запись всей ЦНС');
  await expect(panel.getByRole('img')).toHaveAttribute('data-signal-half-range-uv', '4.27000000e-7');
  await panel.getByText('Координаты контактов записи').click();
  await expect(panel.getByText(/E1: \(2414.208, 475.136, 593.408\)/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('one-cell-recording.png') });
});

test('a saved real one-cell result is shown through the separate backend', async ({ page }, info) => {
  test.skip(!process.env.SIMULATION_E2E_REPLAY_QA, 'Requires a completed owned replay');
  const id = process.env.SIMULATION_E2E_FULL_CNS, replayId = process.env.SIMULATION_E2E_REPLAY_QA;
  for (const path of [`/runs/${id}/replays`, `/runs/${replayId}`]) {
    await page.route(`**/api/simulations/v1${path}`, async route => {
      const response = await page.request.get(`http://localhost:8098/api/simulations/v1${path}`);
      if (path.endsWith('/replays') && response.ok()) {
        const body = await response.json();
        body.items = body.items.filter(item => item.id === replayId);
        await route.fulfill({ status: response.status(), json: body });
      } else {
        await route.fulfill({ status: response.status(), contentType: 'application/json', body: await response.body() });
      }
    });
  }
  await open(page, id);
  await page.getByRole('button', { name: 'Запись', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Дополнительная запись нейрона' });
  await expect(panel).toContainText('Дополнительная запись нейрона 12781', { timeout: 15000 });
  await expect(panel.getByRole('img')).toHaveAttribute('data-current-samples', '1301');
  await expect(panel).toContainText('это не запись всей ЦНС');
  await panel.getByText('Координаты контактов записи').click();
  await expect(panel.getByText(/E1: \(2414.208, 475.136, 593.408\)/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('real-one-cell-recording.png') });
});

test('an unavailable saved run leaves the simulator usable without exposing another record', async ({ page }) => {
  await page.goto('/simulator?run=00000000-0000-4000-8000-000000000000');
  await expect(page.getByRole('alert').filter({ hasText: 'Запись недоступна' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Электроды', exact: true })).toBeVisible();
  await expect(page.getByText('Не удалось подключиться к симулятору')).toHaveCount(0);
});

test('a server failure while opening a run is not treated as a missing record', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000000';
  await page.route(`**/api/simulations/v1/runs/${id}`, route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }));
  await page.goto(`/simulator?run=${id}`);
  await expect(page.getByText('Не удалось подключиться к симулятору', { exact: false })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Запись недоступна', { exact: false })).toHaveCount(0);
});

test('full graph, calculated propagation, rewind and quiet control', async ({ page }, info) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await open(page);
  expect(Number(await scene(page).getAttribute('data-connectome-route-samples'))).toBeGreaterThan(24000 * 2);
  await expect(page.getByRole('button', { name: 'Окно локальной цепи', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Приблизить электроды', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-local-model-visible', 'false');
  await page.getByRole('button', { name: 'Центрировать камеру', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  await seek(page, 60);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-connectome-active-nodes'))).toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath('full-cns-active.png') });
  await seek(page, 0); await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  await expect(scene(page)).toHaveAttribute('data-overview-cells', '166700', { timeout: 120000 });
  await page.waitForTimeout(100);
  const frame = await scene(page).getAttribute('data-render-count'); await page.waitForTimeout(300);
  await expect(scene(page)).toHaveAttribute('data-render-count', frame);
  if (process.env.SIMULATION_E2E_FULL_CNS_QUIET) {
    await open(page, process.env.SIMULATION_E2E_FULL_CNS_QUIET);
    await seek(page, 60); await expect(scene(page)).toHaveAttribute('data-connectome-active-nodes', '0');
    await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  }
  expect(errors).toEqual([]);
});

test('compiled demo receives an authorized saved-run snapshot through the real WebSocket', async ({ page }) => {
  await open(page);
  const result = await page.evaluate(runId => new Promise(resolve => {
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/simulations/v1/runs/${runId}/events`);
    const finish = result => { clearTimeout(timer); socket.close(); resolve(result); };
    const timer = setTimeout(() => finish({ status: 'timeout' }), 15000);
    socket.onerror = () => finish({ status: 'unavailable' });
    socket.onmessage = message => {
      const payload = JSON.parse(message.data);
      if (payload.type === 'snapshot') finish({ status: 'snapshot', id: payload.run.id, state: payload.run.state });
    };
  }), process.env.SIMULATION_E2E_FULL_CNS);
  expect(result).toEqual({ status: 'snapshot', id: process.env.SIMULATION_E2E_FULL_CNS, state: 'completed' });
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

test('native EM view preserves events, hides schematic anatomy and returns for contact placement', async ({ page }, info) => {
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await open(page);
  await seek(page, 38);
  const delivered = await scene(page).getAttribute('data-connectome-delivered-spikes');
  const angles = await scene(page).getAttribute('data-leg-reactions-rad');
  const toggle = page.getByRole('button', { name: 'Исходная ЦНС', exact: true });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(scene(page)).toHaveAttribute('data-coordinate-view', 'native-em-mm');
  await expect(scene(page)).toHaveAttribute('data-body-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-recording-contacts-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-peripheral-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-schematic-connections-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
  await expect(scene(page)).toHaveAttribute('data-leg-reactions-rad', angles);
  const initialScale = Number(await scene(page).getAttribute('data-connectome-point-scale'));
  await scene(page).hover();
  await page.mouse.wheel(0, -450);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-connectome-point-scale'))).toBeGreaterThan(initialScale);
  await page.getByRole('button', { name: 'Нейроны', exact: true }).click();
  await expect(toggle).toBeVisible();
  await page.getByRole('button', { name: 'Нейроны', exact: true }).click();
  await page.screenshot({ path: info.outputPath('native-em-view.png') });
  await page.getByRole('button', { name: 'Тело', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-coordinate-view', 'body-view-only');
  await expect(scene(page)).toHaveAttribute('data-body-visible', 'true');
  await toggle.click();
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-coordinate-view', 'body-view-only');
  await expect(scene(page)).toHaveAttribute('data-recording-contacts-visible', 'true');
  await page.keyboard.press('Escape');
  expect(posts).toBe(0);
});

test('dorsal thorax chooses notum rather than the pooled six-leg sensory input', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Область воздействия', exact: true }).click();
  const bounds = await scene(page).boundingBox(); let thorax = false;
  for (const [x, y] of [[.5, .40], [.52, .38], [.48, .38], [.52, .43], [.54, .42], [.48, .45]]) {
    await scene(page).click({ position: { x: bounds.width * x, y: bounds.height * y } });
    thorax = (await scene(page).getAttribute('data-last-picked-sensory-region')) === 'notum';
    if (thorax) break;
    const picker = page.getByRole('button', { name: 'Область воздействия', exact: true });
    if (await picker.getAttribute('aria-pressed') !== 'true') await picker.click();
  }
  expect(thorax).toBe(true);
  await expect(scene(page)).toHaveAttribute('data-last-picked-sensory-region', 'notum');
  await expect(page.getByText(/Выбрана вся сенсорная популяция спинной поверхности груди/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Область воздействия', exact: true })).toHaveAttribute('aria-pressed', 'false');
});

test('wheel zoom follows the pointer and camera reset restores the original view', async ({ page }) => {
  await open(page);
  const canvas = scene(page), box = await canvas.boundingBox();
  const initial = JSON.parse(await canvas.getAttribute('data-camera-pose'));
  await page.mouse.move(box.x + box.width * .68, box.y + box.height * .35);
  await page.mouse.wheel(0, -240);
  await expect.poll(async () => {
    const next = JSON.parse(await canvas.getAttribute('data-camera-pose'));
    return Math.hypot(...next.target.map((v, i) => v - initial.target[i]));
  }).toBeGreaterThan(.005);
  await page.getByRole('button', { name: 'Центрировать камеру', exact: true }).click();
  await expect.poll(async () => {
    const next = JSON.parse(await canvas.getAttribute('data-camera-pose'));
    return Math.hypot(...next.target.map((v, i) => v - initial.target[i]));
  }).toBeLessThan(.001);
});

test('body geometry download starts while the manifest is still delayed', async ({ page }) => {
  let signalBinary;
  const binaryStarted = new Promise(resolve => { signalBinary = resolve; });
  let overlapped = false;
  await page.route('**/assets/simulator/flybody/scene.bin', async route => {
    signalBinary(); await route.continue();
  });
  await page.route('**/assets/simulator/flybody/scene.json', async route => {
    overlapped = await Promise.race([binaryStarted.then(() => true), new Promise(resolve => setTimeout(() => resolve(false), 5000))]);
    await route.continue();
  });
  await open(page);
  expect(overlapped).toBe(true);
});

test('anatomical camera presets retain model time and orient toward the same target', async ({ page }) => {
  await open(page);
  await seek(page, 30);
  const canvas = scene(page);
  for (const [name, axis, sign] of [['Сверху', 2, 1], ['Сбоку', 1, -1], ['Спереди', 0, 1]]) {
    await page.getByRole('button', { name, exact: true }).click();
    await expect.poll(async () => {
      const pose = JSON.parse(await canvas.getAttribute('data-camera-pose'));
      const delta = pose.position.map((v, i) => v - pose.target[i]);
      return sign * delta[axis] / Math.hypot(...delta);
    }).toBeGreaterThan(.99);
    await expect(canvas).toHaveAttribute('data-model-time-ms', '30.000');
  }
});

test('camera presets synchronize both comparison scenes', async ({ page }) => {
  const id = process.env.SIMULATION_E2E_FULL_CNS_NOTUM;
  const reference = process.env.SIMULATION_E2E_FULL_CNS_NOTUM_REFERENCE;
  test.skip(!id || !reference, 'Requires two compatible owned notum records');
  await page.goto(`/simulator?run=${id}&compare=${reference}&view=comparison`);
  await expect(scene(page)).toHaveCount(2, { timeout: 30000 });
  const canvases = scene(page);
  for (let i = 0; i < 2; i += 1) await expect(canvases.nth(i)).toHaveAttribute('data-connectome-nodes', '166700', { timeout: 45000 });
  for (let i = 0; i < 2; i += 1) await expect(canvases.nth(i)).toHaveAttribute('data-overview-cells', '166700', { timeout: 120000 });
  await page.getByRole('button', { name: 'Сверху', exact: true }).first().click();
  await expect.poll(async () => {
    const poses = await Promise.all([0, 1].map(async i => JSON.parse(await canvases.nth(i).getAttribute('data-camera-pose'))));
    return Math.max(...poses[0].position.map((v, i) => Math.abs(v - poses[1].position[i])));
  }).toBeLessThan(.001);
});

test('comparison reference recovers after a temporary failure without submitting a run', async ({ page }) => {
  const id = process.env.SIMULATION_E2E_FULL_CNS_NOTUM;
  const reference = process.env.SIMULATION_E2E_FULL_CNS_NOTUM_REFERENCE;
  test.skip(!id || !reference, 'Requires two compatible owned notum records');
  let outage = true, posts = 0;
  page.on('request', req => { if (req.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(req.url())) posts += 1; });
  await page.route(`**/api/simulations/v1/runs/${reference}`, async route => {
    if (outage) await route.fulfill({ status: 503, json: { detail: 'temporary outage' } });
    else await route.continue();
  });
  await page.goto(`/simulator?run=${id}&compare=${reference}&view=comparison`);
  const retry = page.getByRole('button', { name: 'Повторить загрузку A', exact: true });
  await expect(retry).toBeVisible({ timeout: 45000 });
  outage = false;
  await retry.click();
  await expect(scene(page)).toHaveCount(2, { timeout: 45000 });
  for (let i = 0; i < 2; i += 1) await expect(scene(page).nth(i)).toHaveAttribute('data-connectome-nodes', '166700', { timeout: 45000 });
  expect(posts).toBe(0);
});

test('body nerve layer preserves CNS positions and shows recorded abdominal and single-leg events', async ({ page }, info) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && /shader|WebGL|THREE/i.test(message.text())) errors.push(message.text()); });
  await open(page);
  await expect(scene(page)).toHaveAttribute('data-peripheral-paths', '8');
  await expect(scene(page)).toHaveAttribute('data-peripheral-readout-cells', '10446');
  await expect(scene(page)).toHaveAttribute('data-peripheral-visible', 'true');
  await seek(page, 29);
  expect(Object.values(JSON.parse(await scene(page).getAttribute('data-peripheral-activity'))).flat().every(count => count === 0)).toBe(true);
  await seek(page, 43);
  expect(JSON.parse(await scene(page).getAttribute('data-peripheral-activity')).abdomen[1]).toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath('abdominal-nerve-response.png') });
  const delivered = await scene(page).getAttribute('data-connectome-delivered-spikes');
  await page.getByRole('button', { name: 'Нервы тела', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-peripheral-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-connectome-visible-nodes', '166700');
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
  await page.getByRole('button', { name: 'Нервы тела', exact: true }).click();
  if (process.env.SIMULATION_E2E_FULL_CNS_FRONT_LEFT) {
    await open(page, process.env.SIMULATION_E2E_FULL_CNS_FRONT_LEFT);
    await expect(scene(page)).toHaveAttribute('data-peripheral-readout-cells', '10446');
    await seek(page, 30);
    const activity = JSON.parse(await scene(page).getAttribute('data-peripheral-activity'));
    expect(activity.front_left).toEqual([151, 0]);
    expect(Object.entries(activity).filter(([region]) => region !== 'front_left').flatMap(([, counts]) => counts).every(count => count === 0)).toBe(true);
    await page.screenshot({ path: info.outputPath('single-leg-nerve-input.png') });
  }
  if (process.env.SIMULATION_E2E_FULL_CNS_QUIET) {
    await open(page, process.env.SIMULATION_E2E_FULL_CNS_QUIET);
    await expect(scene(page)).toHaveAttribute('data-peripheral-readout-cells', '10446');
    await seek(page, 60);
    expect(Object.values(JSON.parse(await scene(page).getAttribute('data-peripheral-activity'))).flat().every(count => count === 0)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test('source joint hierarchy covers the whole body without altering the neural journal', async ({ page }, info) => {
  await open(page); await seek(page, 43);
  const delivered = await scene(page).getAttribute('data-connectome-delivered-spikes');
  const joints = page.getByRole('button', { name: 'Суставы', exact: true });
  await joints.click();
  await expect(scene(page)).toHaveAttribute('data-source-rig-joints', '102');
  await expect(scene(page)).toHaveAttribute('data-source-rig-bodies', '68');
  await expect(scene(page)).toHaveAttribute('data-source-rig-visible', 'true');
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
  await page.screenshot({ path: info.outputPath('source-body-joints.png') });
  await page.getByRole('button', { name: 'Исходная ЦНС', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-source-rig-visible', 'false');
  await expect(joints).toHaveCount(0);
  await page.getByRole('button', { name: 'Тело', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-source-rig-visible', 'true');
  await joints.click();
  await expect(scene(page)).toHaveAttribute('data-source-rig-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
});

test('new demos use exterior recording contacts without rewriting the old internal record', async ({ page }) => {
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await open(page);
  await expect(scene(page)).toHaveAttribute('data-electrode-body-location', 'inside');
  await expect(scene(page)).toHaveAttribute('data-reference-body-location', 'inside');
  await expect(page.getByTestId('internal-recording-contacts')).toBeVisible();
  await page.getByRole('button', { name: 'Новый опыт', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '0');
  await expect(scene(page)).toHaveAttribute('data-electrode-body-location', 'outside');
  await expect(scene(page)).toHaveAttribute('data-reference-body-location', 'outside');
  await expect(scene(page)).toHaveAttribute('data-electrode-surface-aligned', 'true');
  await expect(scene(page)).toHaveAttribute('data-reference-surface-aligned', 'true');
  await expect(page.getByTestId('internal-recording-contacts')).toHaveCount(0);
  await page.getByRole('button', { name: 'Параметры модели', exact: true }).click();
  // react-select renders the selected label beside its empty search input.
  const input = page.getByRole('combobox', { name: 'Сенсорный вход', exact: true });
  await expect(input).toBeVisible();
  await expect(page.getByText('Передняя левая нога', { exact: true })).toBeVisible();
  expect(posts).toBe(0);
});

test('passive contact snaps outside the registered surface and cancellation restores its coordinates', async ({ page }) => {
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await open(page);
  const originalRegion = await scene(page).getAttribute('data-sensory-region');
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  const fields = ['x', 'y', 'z'].map(axis => page.locator(`#contact-electrode-${axis}_um`));
  const original = await Promise.all(fields.map(input => input.inputValue()));
  const bounds = await scene(page).boundingBox(); let snapped = null;
  for (const y of [.44, .36, .52, .28, .6]) {
    for (const x of [.40, .46, .34, .52, .28]) {
      await scene(page).click({ position: { x: bounds.width * x, y: bounds.height * y } });
      const record = await scene(page).getAttribute('data-surface-contact');
      if (record) { snapped = JSON.parse(record); break; }
    }
    if (snapped) break;
  }
  expect(snapped).not.toBeNull();
  expect(snapped.contact).toBe('electrode'); expect(snapped.offset_um).toBe(25);
  const current = await Promise.all(fields.map(input => input.inputValue()));
  current.forEach((value, axis) => expect(Number(value)).toBeCloseTo(snapped.position_um[['x_um', 'y_um', 'z_um'][axis]], 6));
  expect(current).not.toEqual(original);
  await expect(scene(page)).toHaveAttribute('data-electrode-surface-aligned', 'true');
  await expect(scene(page)).toHaveAttribute('data-sensory-region', originalRegion);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  expect(await Promise.all(fields.map(input => input.inputValue()))).toEqual(original);
  await page.keyboard.press('Escape');
  expect(posts).toBe(0);
});

test('the displayed recording keeps its contact positions while edits remain a draft', async ({ page }) => {
  await open(page);
  const original = JSON.parse(await scene(page).getAttribute('data-recording-contact-coordinates'));
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  const field = page.locator('#contact-electrode-x_um');
  const next = Number(await field.inputValue()) + 1;
  await field.fill(String(next));
  await expect.poll(async () => JSON.parse(await scene(page).getAttribute('data-recording-contact-coordinates')).electrode.x_um).toBe(next);
  await expect(page.getByText('Положения в сцене — черновик; сигнал относится к сохранённому расчёту.')).toBeVisible();
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect.poll(async () => JSON.parse(await scene(page).getAttribute('data-recording-contact-coordinates')).electrode.x_um).toBe(original.electrode.x_um);
  await expect(page.getByText('Показаны электроды сохранённого расчёта; изменённые параметры будут использованы при следующем запуске.')).toBeVisible();
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  await expect(field).toHaveValue(String(next));
  await expect.poll(async () => JSON.parse(await scene(page).getAttribute('data-recording-contact-coordinates')).electrode.x_um).toBe(next);
  await page.keyboard.press('Escape');
});

test('manual contact edits do not submit a stale surface anchor', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  const bounds = await scene(page).boundingBox(); let snapped = null;
  for (const y of [.44, .36, .52, .28, .6]) {
    for (const x of [.40, .46, .34, .52, .28]) {
      await scene(page).click({ position: { x: bounds.width * x, y: bounds.height * y } });
      const record = await scene(page).getAttribute('data-surface-contact');
      if (record) { snapped = JSON.parse(record); break; }
    }
    if (snapped) break;
  }
  expect(snapped).not.toBeNull();
  const field = page.locator('#contact-electrode-x_um');
  await field.fill(String(Number(await field.inputValue()) + 1));
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  let payload;
  await page.route('**/api/simulations/v1/runs', async route => {
    if (route.request().method() === 'POST') {
      payload = route.request().postDataJSON();
      await route.fulfill({ status: 422, json: { detail: 'test interception' } });
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Запустить', exact: true }).click();
  await expect.poll(() => payload?.configuration?.placement?.registration?.surface_anchors?.electrode).toBeNull();
});

test('a surface pick records which contact the anchor belongs to', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Электроды', exact: true }).click();
  const bounds = await scene(page).boundingBox();
  for (const [button, key] of [['E1', 'electrode'], ['REF', 'reference']]) {
    await page.getByRole('button', { name: button, exact: true }).click();
    let snapped = null;
    for (const y of [.44, .36, .52, .28, .6]) {
      for (const x of key === 'reference' ? [.46, .52, .34, .40, .28] : [.40, .46, .34, .52, .28]) {
        await scene(page).click({ position: { x: bounds.width * x, y: bounds.height * y } });
        const record = await scene(page).getAttribute('data-surface-contact');
        if (record && JSON.parse(record).contact === key) { snapped = JSON.parse(record); break; }
      }
      if (snapped) break;
    }
    expect(snapped?.contact).toBe(key);
  }
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  let payload;
  await page.route('**/api/simulations/v1/runs', async route => {
    if (route.request().method() === 'POST') {
      payload = route.request().postDataJSON();
      await route.fulfill({ status: 422, json: { detail: 'test interception' } });
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Запустить', exact: true }).click();
  await expect.poll(() => payload?.configuration?.placement?.registration?.surface_anchors?.reference?.contact).toBe('reference');
  expect(payload.configuration.placement.registration.surface_anchors.electrode.contact).toBe('electrode');
});

test('neuron inspection reads exact IDs and events without submitting a calculation', async ({ page }) => {
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await open(page);
  const bounds = await scene(page).boundingBox(); let found = false;
  await page.keyboard.down('Alt');
  for (const y of [.4, .45, .5, .55]) {
    for (const x of [.48, .53, .58, .63, .68]) {
      await page.mouse.move(bounds.x + bounds.width * x, bounds.y + bounds.height * y);
      await page.waitForTimeout(90);
      if (await page.getByRole('tooltip', { name: 'Сведения о нейроне', exact: true }).isVisible()) { found = true; break; }
    }
    if (found) break;
  }
  expect(found).toBe(true);
  const id = await scene(page).getAttribute('data-inspected-neuron');
  expect(id).toMatch(/^[1-9]\d*$/);
  await expect(page.getByRole('tooltip', { name: 'Сведения о нейроне', exact: true })).toContainText(`MaleCNS · ${id}`);
  await expect(page.getByRole('tooltip', { name: 'Сведения о нейроне', exact: true })).toContainText('EM, мкм (приблизительно)');
  await expect(page.getByRole('tooltip', { name: 'Сведения о нейроне', exact: true })).toContainText('Спайков к 0.00 мс: 0');
  await page.keyboard.up('Alt');
  await expect(page.getByRole('tooltip', { name: 'Сведения о нейроне', exact: true })).toHaveCount(0);
  expect(posts).toBe(0);
});

test('overlapping neurons can be cycled and the selected candidate opened', async ({ page }) => {
  await open(page);
  const bounds = await scene(page).boundingBox();
  let position = null;
  await page.keyboard.down('Alt');
  for (const y of [.4, .45, .5, .55]) {
    for (const x of [.48, .53, .58, .63, .68]) {
      const point = { x: bounds.x + bounds.width * x, y: bounds.y + bounds.height * y };
      await page.mouse.move(point.x, point.y); await page.waitForTimeout(100);
      if (Number(await scene(page).getAttribute('data-inspection-candidates')) > 1) {
        position = point; break;
      }
    }
    if (position) break;
  }
  expect(position).not.toBeNull();
  const first = await scene(page).getAttribute('data-inspected-neuron');
  await page.keyboard.press('ArrowDown');
  await expect(scene(page)).toHaveAttribute('data-inspection-candidate-index', '1');
  const second = await scene(page).getAttribute('data-inspected-neuron');
  expect(second).not.toBe(first);
  await page.mouse.click(position.x, position.y);
  await expect(scene(page)).toHaveAttribute('data-selected-neuron-id', second);
  await page.keyboard.up('Alt');
});

test('a selected neuron opens bounded outgoing adjacency from the registered graph', async ({ page }) => {
  await open(page);
  const bounds = await scene(page).boundingBox(); let found = false;
  await page.keyboard.down('Alt');
  for (const y of [.4, .45, .5, .55]) {
    for (const x of [.48, .53, .58, .63, .68]) {
      await page.mouse.move(bounds.x + bounds.width * x, bounds.y + bounds.height * y);
      await page.waitForTimeout(100);
      if (await page.getByRole('tooltip', { name: 'Сведения о нейроне' }).isVisible()) {
        await page.mouse.click(bounds.x + bounds.width * x, bounds.y + bounds.height * y);
        found = true; break;
      }
    }
    if (found) break;
  }
  await page.keyboard.up('Alt');
  expect(found).toBe(true);
  const panel = page.getByRole('region', { name: 'Исходящие связи нейрона' });
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/Исходящих связей:/)).toBeVisible({ timeout: 45000 });
  await panel.getByRole('button', { name: 'Закрыть' }).click();
  await expect(panel).toHaveCount(0);
});

test('neuron adjacency is accessible by keyboard and rejects an unknown ID', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Открыть нейрон по ID', exact: true }).focus();
  await page.keyboard.press('Enter');
  const input = page.getByRole('textbox', { name: 'ID нейрона' });
  await input.fill('9999999999999999999');
  await input.press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: 'Нейрон с таким ID отсутствует' })).toBeVisible();
  await input.fill('15427');
  await input.press('Enter');
  const panel = page.getByRole('region', { name: 'Исходящие связи нейрона' });
  await expect(panel.getByText('Нейрон 15427')).toBeVisible();
  await expect(panel.getByText('Исходящих связей: 143')).toBeVisible({ timeout: 45000 });
  await expect(panel.getByText(/→/)).toHaveCount(20);
  await expect(scene(page)).toHaveAttribute('data-selected-connection-lines', '0');
  await expect(panel.getByText(/Связи перечислены ниже/)).toBeVisible();
  const focus = panel.getByRole('button', { name: 'Приблизить нейрон' });
  await expect(focus).toBeEnabled();
  const before = JSON.parse(await scene(page).getAttribute('data-camera-pose'));
  await focus.click();
  await expect.poll(async () => JSON.parse(await scene(page).getAttribute('data-camera-pose')).target).not.toEqual(before.target);
  const after = JSON.parse(await scene(page).getAttribute('data-camera-pose'));
  expect(Math.hypot(...after.position.map((value, i) => value - after.target[i]))).toBeCloseTo(.6, 3);
  await panel.getByRole('button', { name: 'Входящие', exact: true }).click();
  const incomingPanel = page.getByRole('region', { name: 'Входящие связи нейрона' });
  await expect(incomingPanel.getByText('Входящих связей: 76')).toBeVisible({ timeout: 45000 });
  await expect(incomingPanel.getByText(/←/)).toHaveCount(20);
  const neighbor = incomingPanel.getByRole('button', { name: /^Открыть нейрон \d+$/ }).first();
  const neighborId = (await neighbor.getAttribute('aria-label')).replace('Открыть нейрон ', '');
  await neighbor.click();
  await expect(page.getByText(`Нейрон ${neighborId}`, { exact: true })).toBeVisible();
  await expect(page.getByText(/Выделена зарегистрированная точка отростка|Выделена точка по зарегистрированным координатам|Выделенное положение нейрона показано условно|Для этого нейрона нет отображаемого положения|В исходном виде положение этого нейрона не зарегистрировано/)).toBeVisible();
  await expect(scene(page)).toHaveAttribute('data-selected-neuron-id', neighborId);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-selected-neuron-index'))).toBeGreaterThanOrEqual(0);
});

test('overview loads source fragments for the entire registered CNS', async ({ page }, testInfo) => {
  test.setTimeout(180000);
  await open(page);
  await expect(scene(page)).toHaveAttribute('data-overview-cells', '166700', { timeout: 120000 });
  await expect.poll(async () => Number(await scene(page).getAttribute('data-overview-segments'))).toBeGreaterThan(1000000);
  await expect(page.getByTitle('Обзор: до восьми исходных сегментов на нейрон')).toContainText('обзор отростков 166 700');
  await page.getByRole('button', { name: 'Структура и границы', exact: true }).click();
  await expect(page.getByText(/до восьми исходных сегментов на нейрон/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('cns-overview.png') });
  await page.getByRole('button', { name: 'Нейроны', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-overview-cells', '0');
  await page.getByRole('button', { name: 'Нейроны', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-overview-cells', '166700');
});

test('verified neuropil regions load and follow native view without changing the saved run', async ({ page }, info) => {
  test.setTimeout(180000);
  await open(page);
  const toggle = page.getByRole('button', { name: 'Области ЦНС', exact: true });
  await toggle.click();
  await expect(scene(page)).toHaveAttribute('data-neuropil-regions', '114', { timeout: 120000 });
  const picker = page.getByRole('combobox', { name: 'Область нейропиля' });
  await picker.fill('LegNp(T1)(L)');
  await page.getByRole('option', { name: 'LegNp(T1)(L)', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-neuropil-regions', '1');
  const cameraBefore = await scene(page).getAttribute('data-camera-pose');
  await page.getByRole('button', { name: 'Приблизить', exact: true }).click();
  await expect.poll(() => scene(page).getAttribute('data-camera-pose')).not.toBe(cameraBefore);
  await page.screenshot({ path: info.outputPath('neuropil-body.png') });
  await page.getByRole('button', { name: 'Исходная ЦНС', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-coordinate-view', 'native-em-mm');
  await expect(scene(page)).toHaveAttribute('data-neuropil-regions', '1');
  await page.screenshot({ path: info.outputPath('neuropil-native.png') });
  await toggle.click();
  await expect(scene(page)).toHaveAttribute('data-neuropil-regions', '0');
});

test('selected neuron loads its verified original morphology into the scene', async ({ page }, testInfo) => {
  await open(page);
  await page.getByRole('button', { name: 'Открыть нейрон по ID', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'ID нейрона' });
  await input.fill('12781');
  await input.press('Enter');
  await expect(page.getByText(/Исходная SWC-морфология/)).toBeVisible({ timeout: 45000 });
  await expect.poll(async () => Number(await scene(page).getAttribute('data-selected-morphology-vertices'))).toBe(15945);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-neighbor-morphology-vertices')), { timeout: 45000 }).toBeGreaterThan(0);
  await expect(page.getByText('Морфология соседних нейронов: 20 из 20')).toBeVisible({ timeout: 45000 });
  await expect(page.getByText('Прогнозируемые синапсы: 1275 из 1275')).toBeVisible({ timeout: 180000 });
  await expect(scene(page)).toHaveAttribute('data-synapse-points', '1275');
  await seek(page, 32);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-neighbor-morphology-active'))).toBeGreaterThan(0);
  await seek(page, 0);
  await expect(scene(page)).toHaveAttribute('data-neighbor-morphology-active', '0');
  await page.getByRole('button', { name: 'Приблизить нейрон' }).click();
  await page.screenshot({ path: testInfo.outputPath('selected-morphology.png') });
  await page.getByRole('button', { name: 'Исходная ЦНС', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-selected-morphology-vertices', '15945');
  await expect(scene(page)).toHaveAttribute('data-selected-morphology-visible', 'true');
  await page.getByRole('region', { name: 'Исходящие связи нейрона' }).getByRole('button', { name: 'Входящие', exact: true }).click();
  await expect(page.getByText('Прогнозируемые синапсы: 356 из 356')).toBeVisible({ timeout: 45000 });
  await expect(scene(page)).toHaveAttribute('data-synapse-points', '356');
  await page.getByRole('region', { name: 'Входящие связи нейрона' }).getByRole('button', { name: 'Закрыть' }).click();
  await expect(scene(page)).toHaveAttribute('data-selected-morphology-vertices', '0');
  await expect(scene(page)).toHaveAttribute('data-synapse-points', '0');
});

test('neuron selection shows reconstructed neighbors without straight connection lines', async ({ page }) => {
  await open(page);
  await page.getByText('0,02×', { exact: true }).click();
  await page.getByRole('option', { name: '0,01×' }).click();
  await expect(page.getByText('0,01×', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Открыть нейрон по ID', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'ID нейрона' });
  await input.fill('802759');
  await input.press('Enter');
  await expect(page.getByText(/Связи перечислены ниже/)).toBeVisible({ timeout: 45000 });
  await expect.poll(async () => Number(await scene(page).getAttribute('data-synapse-points')), { timeout: 45000 }).toBeGreaterThan(0);
  await expect(scene(page)).toHaveAttribute('data-selected-connection-lines', '0');
  await seek(page, 29);
  await expect(scene(page)).toHaveAttribute('data-active-synapse-points', '0');
  await seek(page, 30);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-active-synapse-points'))).toBeGreaterThan(0);
  await seek(page, 0);
  await expect(scene(page)).toHaveAttribute('data-active-synapse-points', '0');
  await expect(scene(page)).toHaveAttribute('data-selected-connection-lines', '0');
  await page.getByRole('region', { name: 'Исходящие связи нейрона' }).getByRole('button', { name: 'Закрыть' }).click();
  await expect(scene(page)).toHaveAttribute('data-selected-connection-lines', '0');
});

test.describe('injected source-arbor outage', () => {
// A controlled network failure must reach the route handler rather than a SW cache.
test.use({ serviceWorkers: 'block' });

test('unavailable source joints retain body and CNS with read-only recovery', async ({ page }) => {
  let unavailable = true, posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await page.route('**/assets/simulator/flybody/rig.json', async route => {
    if (unavailable) await route.fulfill({ status: 503, body: '' }); else await route.continue();
  });
  await open(page); await seek(page, 43);
  const delivered = await scene(page).getAttribute('data-connectome-delivered-spikes');
  await page.getByRole('button', { name: 'Суставы', exact: true }).click();
  const retry = page.getByRole('button', { name: 'Повторить загрузку суставов', exact: true });
  await expect(retry).toBeVisible();
  await expect(scene(page)).toHaveAttribute('data-source-rig-visible', 'false');
  await expect(scene(page)).toHaveAttribute('data-body-visible', 'true');
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '166700');
  unavailable = false; await retry.click();
  await expect(scene(page)).toHaveAttribute('data-source-rig-joints', '102');
  await expect(scene(page)).toHaveAttribute('data-source-rig-visible', 'true');
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
  expect(posts).toBe(0);
});

test('missing peripheral registry keeps the schematic paths without invented activity and recovers read-only', async ({ page }) => {
  let unavailable = true, posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await page.route('**/assets/simulator/malecns/peripheral.json', async route => {
    if (unavailable) await route.fulfill({ status: 503, body: '' }); else await route.continue();
  });
  await open(page); await seek(page, 43);
  const retry = page.getByRole('button', { name: 'Повторить загрузку нервных популяций', exact: true });
  await expect(retry).toBeVisible();
  await expect(scene(page)).toHaveAttribute('data-peripheral-visible', 'true');
  await expect(scene(page)).toHaveAttribute('data-peripheral-readout-cells', '0');
  expect(Object.values(JSON.parse(await scene(page).getAttribute('data-peripheral-activity'))).flat().every(count => count === 0)).toBe(true);
  unavailable = false; await retry.click();
  await expect(scene(page)).toHaveAttribute('data-peripheral-readout-cells', '10446');
  expect(JSON.parse(await scene(page).getAttribute('data-peripheral-activity')).abdomen[1]).toBeGreaterThan(0);
  expect(posts).toBe(0);
});
test('source sensory arbors recover independently without altering the saved network events', async ({ page }) => {
  let unavailable = true, posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await page.route('**/assets/simulator/malecns/arbors.json', async route => {
    if (unavailable) await route.fulfill({ status: 503, body: '' }); else await route.continue();
  });
  await open(page); await seek(page, 30);
  const delivered = await scene(page).getAttribute('data-connectome-delivered-spikes');
  await expect(page.getByRole('button', { name: 'Повторить загрузку отростков', exact: true })).toBeVisible();
  await expect(scene(page)).toHaveAttribute('data-connectome-arbor-cells', '0');
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
  unavailable = false;
  await page.getByRole('button', { name: 'Повторить загрузку отростков', exact: true }).click();
  await expect.poll(async () => Number(await scene(page).getAttribute('data-connectome-arbor-cells'))).toBeGreaterThan(0);
  expect(Number(await scene(page).getAttribute('data-connectome-arbor-vertices'))).toBeGreaterThan(1000);
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', delivered);
  expect(posts).toBe(0);
});

test('notum recording displays its registered input arbors without substituting leg afferents', async ({ page }, info) => {
  test.skip(!process.env.SIMULATION_E2E_FULL_CNS_NOTUM, 'Requires an owned completed notum record');
  await open(page, process.env.SIMULATION_E2E_FULL_CNS_NOTUM);
  await expect(page.getByText(/Вход: Спинная поверхность груди/)).toBeVisible();
  await expect(scene(page)).toHaveAttribute('data-connectome-arbor-cells', '214', { timeout: 30000 });
  await expect(scene(page)).toHaveAttribute('data-connectome-arbor-vertices', '141786');
  await seek(page, 0);
  await expect(scene(page)).toHaveAttribute('data-notum-highlight', 'false');
  await seek(page, 30);
  await expect.poll(async () => Number(await scene(page).getAttribute('data-connectome-active-inputs'))).toBeGreaterThan(0);
  await expect(scene(page)).toHaveAttribute('data-notum-highlight', 'true');
  await page.screenshot({ path: info.outputPath('notum-active.png') });
  await seek(page, 0);
  await expect(scene(page)).toHaveAttribute('data-notum-highlight', 'false');
});

test('head motor events are shown separately without claiming a head movement', async ({ page }) => {
  test.skip(!process.env.SIMULATION_E2E_FULL_CNS_HEAD, 'Requires an owned completed head-input record');
  await open(page, process.env.SIMULATION_E2E_FULL_CNS_HEAD);
  await page.getByRole('button', { name: 'Структура и границы', exact: true }).click();
  const text = page.getByTestId('neck-motor-events');
  await expect(text).toContainText('Движение головы по ним пока не рассчитывается.');
  await seek(page, 0); await expect(text).toContainText('0 событий за последние 6 мс');
  await seek(page, 42); await expect(text).not.toContainText('0 событий за последние 6 мс');
  await seek(page, 0); await expect(text).toContainText('0 событий за последние 6 мс');
});

test('missing motor annotations freeze the pose without an HH fallback and recover read-only', async ({ page }) => {
  let unavailable = true, posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  await page.route('**/assets/simulator/malecns/motor.json', async route => {
    if (unavailable) await route.fulfill({ status: 503, body: '' }); else await route.continue();
  });
  await open(page);
  await expect(page.getByRole('button', { name: 'Повторить загрузку моторных популяций', exact: true })).toBeVisible();
  await seek(page, 40);
  await expect(scene(page)).toHaveAttribute('data-pose-controller', 'unavailable');
  expect(Object.values(JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'))).every(angle => angle === 0)).toBe(true);
  expect(Number(await scene(page).getAttribute('data-connectome-delivered-spikes'))).toBeGreaterThan(0);
  unavailable = false;
  await page.getByRole('button', { name: 'Повторить загрузку моторных популяций', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-pose-controller', 'male-cns-motor-display-v1');
  await expect.poll(async () => Object.values(JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'))).some(angle => angle > 0)).toBe(true);
  expect(posts).toBe(0);
});
});

test('calculated input precedes network response and limb cues start at registered motor events', async ({ page }) => {
  const recordResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/simulations/v1/runs/${process.env.SIMULATION_E2E_FULL_CNS}` && response.request().method() === 'GET');
  const bufferResponse = page.waitForResponse(response => new RegExp(`/api/simulations/v1/runs/${process.env.SIMULATION_E2E_FULL_CNS}/artifacts/[^/]+$`).test(new URL(response.url()).pathname));
  const motorResponse = page.waitForResponse('**/assets/simulator/malecns/motor.json');
  await open(page);
  const response = await recordResponse;
  expect(response.ok()).toBe(true);
  const saved = await response.json(), preview = saved.result.preview;
  // Inspect the exact download used by the scene, not a second 5 MB transfer
  // competing with it. Browser response errors also omit request credentials.
  const binaryResponse = await bufferResponse;
  expect(binaryResponse.ok()).toBe(true);
  const bytes = await binaryResponse.body(), layout = preview.connectome.binary.arrays;
  const integer = (field, i) => bytes.readInt32LE(layout[field].offset + i * 4);
  const time = i => bytes.readFloatLE(layout.spike_times_ms.offset + i * 4);
  const inputs = new Set(Array.from({ length: layout.input_indices.count }, (_, i) => integer('input_indices', i)));
  const first = time(0); let firstCount = 0, outside = Infinity;
  for (let i = 0; i < layout.spike_neurons.count; i += 1) {
    const node = integer('spike_neurons', i);
    if (time(i) === first) { expect(inputs.has(node)).toBe(true); firstCount += 1; }
    if (!inputs.has(node)) outside = Math.min(outside, time(i));
  }
  expect(outside).toBeGreaterThanOrEqual(first + preview.connectome.synaptic_delay_ms);
  await seek(page, first - 1);
  await expect(scene(page)).toHaveAttribute('data-connectome-delivered-spikes', '0');
  await seek(page, first);
  await expect(scene(page)).toHaveAttribute('data-connectome-active-inputs', String(firstCount));
  await expect(scene(page)).toHaveAttribute('data-connectome-active-nodes', String(firstCount));
  expect(Object.values(JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'))).every(angle => angle === 0)).toBe(true);
  const firstProjection = Math.min(...preview.spikes.map(event => event.time_ms));
  const registry = await (await motorResponse).json();
  const motor = new Map(registry.cells.map(cell => [cell.id, cell.region]));
  const motorEvents = [];
  for (let i = 0; i < layout.spike_neurons.count; i += 1) {
    const index = integer('spike_neurons', i);
    const id = bytes.readBigUInt64LE(layout.node_ids.offset + index * 8).toString();
    if (motor.has(id)) motorEvents.push({ time: time(i), region: motor.get(id) });
  }
  expect(motorEvents.length).toBeGreaterThan(0);
  const firstMotor = motorEvents[0].time;
  expect(firstMotor).toBeGreaterThan(firstProjection);
  await expect(scene(page)).toHaveAttribute('data-pose-controller', 'male-cns-motor-display-v1');
  await seek(page, Number((Math.ceil((firstProjection + .001) / saved.configuration.dt_ms) * saved.configuration.dt_ms).toFixed(3)));
  expect(Object.values(JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'))).every(angle => angle === 0)).toBe(true);
  await seek(page, firstMotor);
  const responding = new Set(motorEvents.filter(event => event.time === firstMotor).map(event => event.region));
  const angles = JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'));
  const regions = ['front_left', 'front_right', 'middle_left', 'middle_right', 'hind_left', 'hind_right'];
  ['T1_left', 'T1_right', 'T2_left', 'T2_right', 'T3_left', 'T3_right'].forEach((name, index) => {
    if (responding.has(regions[index])) expect(angles['coxa_' + name]).toBeGreaterThan(0);
    else expect(angles['coxa_' + name]).toBe(0);
  });
  await expect(page.locator('canvas[data-motion-source]')).toHaveAttribute('data-motion-source', 'male-cns-motor-display-v1');
});

test('single-leg input keeps other limbs quiet in the recorded front-left scenario', async ({ page }, info) => {
  test.skip(!process.env.SIMULATION_E2E_FULL_CNS_FRONT_LEFT, 'Requires an owned completed front-left record');
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && /\/api\/simulations\/v1\/runs$/.test(request.url())) posts += 1; });
  const id = process.env.SIMULATION_E2E_FULL_CNS_FRONT_LEFT;
  await open(page, id);
  await expect(scene(page)).toHaveAttribute('data-sensory-region', 'front_left');
  await expect(scene(page)).toHaveAttribute('data-electrode-body-location', 'outside');
  await expect(scene(page)).toHaveAttribute('data-reference-body-location', 'outside');
  await expect(scene(page)).toHaveAttribute('data-first-motor-event-ms', /^[1-9]\d*(\.\d+)?$/);
  const first = Number(await scene(page).getAttribute('data-first-motor-event-ms'));
  expect(first).toBeGreaterThan(30);
  await seek(page, first - 1);
  expect(Object.values(JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'))).every(angle => angle === 0)).toBe(true);
  await seek(page, first);
  const angles = JSON.parse(await scene(page).getAttribute('data-leg-reactions-rad'));
  expect(angles.coxa_T1_left).toBeGreaterThan(0);
  for (const [name, angle] of Object.entries(angles)) if (name !== 'coxa_T1_left') expect(angle).toBe(0);
  await page.getByRole('button', { name: 'Структура и границы', exact: true }).click();
  await expect(page.getByTestId('causal-onsets')).toContainText('вход 30 → вне входа 33 → моторные 50');
  await page.screenshot({ path: info.outputPath('front-left-motor-response.png') });
  expect(posts).toBe(0);
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
  await expect(scene(page)).toHaveAttribute('data-local-model-visible', 'false');
  unavailable = false;
  await page.getByRole('button', { name: 'Повторить загрузку коннектома', exact: true }).click();
  await expect(scene(page)).toHaveAttribute('data-connectome-nodes', '166700');
  expect(posts).toBe(0);
});

test('abdominal cells are distinguished from an unavailable tactile input', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: 'Параметры модели', exact: true }).click();
  await expect(page.getByText(/Брюшные сенсорные клетки входят в сеть/)).toBeVisible();
  await page.getByRole('combobox', { name: 'Сенсорный вход', exact: true }).click();
  await expect(page.getByRole('option', { name: 'Брюшко · тактильный вход не определён', exact: true })).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('Escape');
});

test('both full-network scenes restore from the URL with the same clock', async ({ page }, info) => {
  test.skip(!process.env.SIMULATION_E2E_FULL_CNS_MOVED, 'Requires an owned moved-electrode record');
  await page.goto('/simulator?run=' + process.env.SIMULATION_E2E_FULL_CNS_MOVED + '&compare=' + process.env.SIMULATION_E2E_FULL_CNS + '&view=comparison');
  await expect(scene(page)).toHaveCount(2, { timeout: 30000 });
  for (const canvas of await scene(page).all()) await expect(canvas).toHaveAttribute('data-connectome-nodes', '166700', { timeout: 30000 });
  await page.getByLabel('Время воспроизведения', { exact: true }).evaluate(input => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '60');
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  for (const canvas of await scene(page).all()) await expect(canvas).toHaveAttribute('data-model-time-ms', '60.000');
  await page.screenshot({ path: info.outputPath('full-cns-pair.png') });
});
