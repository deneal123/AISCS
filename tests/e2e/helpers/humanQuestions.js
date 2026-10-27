const { expect } = require('@playwright/test');
const SOURCE = '55555555-5555-4555-8555-555555555555';
const CHILD = '66666666-6666-4666-8666-666666666666';

async function questionFixture(page, { threadId, projectId, surface }) {
  const snapshot = { question_id: '77777777-7777-4777-8777-777777777777', source_job_id: SOURCE,
    surface, project_id: projectId, prompt: 'Какую структуру проекта использовать?',
    choices: [{ id: 'small', label: 'Минимальная структура' }, { id: 'full', label: 'Полная структура с примерами' }],
    state: 'pending', expires_at: new Date(Date.now() + 300000).toISOString(), resume_job_id: null };
  const state = { snapshot, question: { ...snapshot }, answers: [], cancels: 0, reads: 0, taskReads: 0, taskState: 'PENDING', history: null,
    cost: { offer_id: '88888888-8888-4888-8888-888888888888', state: 'not_required', estimated_credits: 1, expires_at: snapshot.expires_at }, costReads: 0, decisions: [], stops: [] };
  const base = `/api/chats/${threadId}/runs/${SOURCE}/questions/${snapshot.question_id}`;
  await page.route(url => url.pathname.startsWith(base), async route => {
    const request = route.request(); const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith('/cost')) {
      if (request.method() === 'GET') {
        state.costReads += 1;
        if (state.costUnavailable) { await route.abort(); return; }
      }
      else {
        const body = request.postDataJSON(); state.decisions.push(body);
        if (body.decision === 'refresh') state.cost = { ...state.cost, state: 'pending', offer_id: '99999999-9999-4999-8999-999999999999', expires_at: new Date(Date.now() + 30000).toISOString() };
        else state.cost = { ...state.cost, state: body.decision === 'accept' ? 'accepted' : 'declined' };
        if (state.loseDecision) { state.loseDecision = false; await route.abort(); return; }
      }
      await route.fulfill({ json: state.cost }); return;
    }
    if (request.method() === 'GET') { state.reads += 1; await route.fulfill({ json: state.question }); return; }
    if (pathname.endsWith('/answer')) {
      state.answers.push(request.postDataJSON());
      state.question = { ...snapshot, state: 'accepted', resume_job_id: CHILD };
      if (state.loseAnswer) { state.loseAnswer = false; await route.abort(); return; }
    } else {
      state.cancels += 1; state.question = { ...snapshot, state: 'cancelled' };
    }
    await route.fulfill({ json: state.question });
  });
  await page.route(`**/api/jobs/v1/task/${CHILD}/status`, async route => {
    state.taskReads += 1;
    if (state.taskUnavailable) { await route.abort(); return; }
    await route.fulfill({ json: { task_id: CHILD, state: state.taskState, result: null } });
  });
  await page.route(`**/api/jobs/v1/task/${CHILD}/cancel`, async route => {
    state.stops.push(route.request().url());
    state.taskState = 'FAILURE';
    if (state.loseStop) { state.loseStop = false; await route.abort(); return; }
    await route.fulfill({ json: { task_id: CHILD, cancelled: true } });
  });
  await page.route(url => url.pathname === `/api/chats/${threadId}`, async route => {
    if (state.history) await route.fulfill({ json: { messages: state.history } });
    else await route.fallback();
  });
  return state;
}

async function parkQuestion(page, socket, question, requests) {
  const transport = typeof socket === 'function' ? socket : () => socket;
  await expect.poll(() => Boolean(transport())).toBe(true);
  await expect(page.getByRole('status', { name: 'На связи', exact: true })).toBeVisible();
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Подготовь проект и уточни структуру');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  transport().send(JSON.stringify({ type: 'job_created', job_id: SOURCE, celery_task_id: SOURCE,
    ...(question.surface === 'pdf' ? { document_project: question.project_id } : {}) }));
  transport().send(JSON.stringify({ type: 'agent_reply', job_id: SOURCE, reply: question.prompt,
    metadata: { execution_status: 'waiting_user', human_question: question,
      [question.surface === 'pdf' ? 'document_project' : 'ide_repository']: question.project_id } }));
  const panel = page.getByRole('region', { name: 'Вопрос агента', exact: true });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Минимальная структура', exact: true })).toBeEnabled();
  await expect(input).toBeHidden();
  return panel;
}

async function exerciseUnknownCostStop(page, question, requests, info) {
  const panel = page.getByRole('region', { name: 'Вопрос агента', exact: true });
  await panel.getByRole('button', { name: 'Минимальная структура', exact: true }).click();
  await panel.getByRole('button', { name: 'Продолжить', exact: true }).click();
  const consent = page.getByRole('region', { name: 'Подтверждение стоимости', exact: true });
  question.loseDecision = true;
  await consent.getByRole('button', { name: 'Подтвердить запуск', exact: true }).click();
  const stop = consent.getByRole('button', { name: 'Остановить', exact: true });
  await expect(stop).toBeEnabled();
  const before = await consent.boundingBox();
  const footer = await stop.boundingBox();
  const costReads = question.costReads;
  question.costUnavailable = true; question.taskUnavailable = true; question.loseStop = true;
  await stop.click();
  await expect(consent.getByRole('heading', { name: 'Остановка продолжения', exact: true })).toBeVisible();
  await expect(consent.getByText('Не удалось проверить продолжение. Результат остановки пока неизвестен.', { exact: true })).toBeVisible();
  await expect(consent.getByRole('button', { name: 'Повторить остановку', exact: true })).toBeEnabled();
  expect(await consent.boundingBox()).toEqual(before);
  expect(await consent.getByRole('button', { name: 'Повторить остановку', exact: true }).boundingBox()).toEqual(footer);
  await page.screenshot({ path: info.outputPath('unknown-cost-stop.png'), animations: 'disabled' });
  await page.addScriptTag({ content: require('axe-core').source });
  const violations = await page.evaluate(async () => (await window.axe.run(
    document.querySelector('[data-testid="human-question-panel"]'))).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)));
  expect(violations).toEqual([]);
  expect(question.stops).toHaveLength(1); expect(question.decisions).toHaveLength(1);
  expect(question.answers).toHaveLength(1); expect(requests).toHaveLength(1);
  question.taskUnavailable = false;
  await consent.getByRole('button', { name: 'Проверить состояние', exact: true }).click();
  await expect(consent).toHaveCount(0);
  await expect(page.getByText('Продолжение завершено после запроса остановки. Подробности — в Чате.', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeFocused();
  expect(question.stops).toHaveLength(1); expect(question.decisions).toHaveLength(1);
  expect(question.costReads).toBe(costReads); expect(requests).toHaveLength(1);
}

module.exports = { questionFixture, parkQuestion, exerciseUnknownCostStop, SOURCE, CHILD };
