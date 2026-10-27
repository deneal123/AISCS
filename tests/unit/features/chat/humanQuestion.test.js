import { humanQuestionTarget, latestHumanQuestion, parseHumanQuestion, sameHumanQuestion } from '@features/chat/model/humanQuestion';

const question = () => ({ question_id: '11111111-1111-4111-8111-111111111111', source_job_id: '22222222-2222-4222-8222-222222222222',
  project_id: '33333333-3333-4333-8333-333333333333', surface: 'ide', prompt: 'Какую структуру создать?',
  choices: [{ id: 'small', label: 'Минимальная' }, { id: 'full', label: 'Полная' }], state: 'pending',
  expires_at: '2026-10-20T10:00:00+00:00', resume_job_id: null });

test('parses only the bounded public question and allows state transitions, not foreign identity', () => {
  const raw = question(); expect(parseHumanQuestion(raw)).toEqual(raw);
  expect(parseHumanQuestion({ ...raw, token: 'private' })).toBeNull();
  expect(parseHumanQuestion({ ...raw, choices: [raw.choices[0]] })).toBeNull();
  expect(parseHumanQuestion({ ...raw, choices: [raw.choices[0], raw.choices[0]] })).toBeNull();
  expect(parseHumanQuestion({ ...raw, resume_job_id: raw.question_id })).toBeNull();
  expect(parseHumanQuestion({ ...raw, prompt: 'x'.repeat(1001) })).toBeNull();
  expect(sameHumanQuestion(raw, { ...raw, state: 'expired' }).state).toBe('expired');
  expect(sameHumanQuestion(raw, { ...raw, project_id: raw.question_id })).toBeNull();
});

test('a newer persisted child result wins over an older retained live question', () => {
  const paused = { type: 'agent', timestamp: '2026-10-19T10:00:00Z', metadata: { human_question: question() } };
  expect(latestHumanQuestion([paused], 'ide')).toEqual(question());
  expect(latestHumanQuestion([paused], 'pdf')).toBeNull();
  expect(latestHumanQuestion([{ type: 'agent', timestamp: '2026-10-19T10:01:00Z', content: 'Готово' }, paused], 'ide')).toBeNull();
  expect(latestHumanQuestion([paused, { type: 'user', content: 'Новый запрос' }], 'ide')).toBeNull();
});

test('target projection carries only the current project context, never client authority', () => {
  const raw = question();
  const context = { repository_id: raw.project_id, generation: 'a'.repeat(64), token: 'PRIVATE', thread_id: 'PRIVATE' };
  expect(humanQuestionTarget(raw, context)).toEqual({ ide_context: { repository_id: raw.project_id, generation: 'a'.repeat(64) } });
  expect(humanQuestionTarget(raw, { ...context, blocked: true })).toBeNull();
  const pdf = { ...raw, surface: 'pdf' };
  expect(humanQuestionTarget(pdf, { project_id: raw.project_id, path: 'documents/test', expected_revision: 'r1', token: 'PRIVATE' }))
    .toEqual({ document_context: { path: 'documents/test', expected_revision: 'r1' } });
});
