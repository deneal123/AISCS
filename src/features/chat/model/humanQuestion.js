import { latestTimelineMessage } from '../utils/latestTimelineMessage';

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const fields = ['question_id', 'source_job_id', 'surface', 'project_id', 'prompt', 'choices', 'state', 'expires_at', 'resume_job_id'];
const record = value => value && typeof value === 'object' && !Array.isArray(value);
const plain = (value, max) => typeof value === 'string' && value.trim() === value && value.length > 0
  && value.length <= max && !Array.from(value).some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127);
const uuid = value => typeof value === 'string' && UUID.test(value) && value !== '00000000-0000-0000-0000-000000000000';

/** Closed public projection only. Capabilities, answers and transcript are never UI metadata. */
export function parseHumanQuestion(raw) {
  if (!record(raw) || Object.keys(raw).length !== fields.length || fields.some(key => !Object.hasOwn(raw, key))
    || !['question_id', 'source_job_id', 'project_id'].every(key => uuid(raw[key]))
    || !['ide', 'pdf'].includes(raw.surface) || !['pending', 'accepted', 'cancelled', 'expired'].includes(raw.state)
    || !plain(raw.prompt, 1000) || !Array.isArray(raw.choices) || ![0, 2, 3].includes(raw.choices.length)
    || typeof raw.expires_at !== 'string' || !Number.isFinite(Date.parse(raw.expires_at))
    || (raw.state === 'accepted' ? !uuid(raw.resume_job_id) : raw.resume_job_id !== null)) return null;
  const ids = new Set();
  for (const choice of raw.choices) {
    if (!record(choice) || Object.keys(choice).length !== 2 || !plain(choice.id, 32)
      || !/^[a-z][a-z0-9_-]*$/.test(choice.id) || !plain(choice.label, 120) || ids.has(choice.id)) return null;
    ids.add(choice.id);
  }
  return { ...raw, choices: raw.choices.map(choice => ({ id: choice.id, label: choice.label })) };
}

export function latestHumanQuestion(messages, surface) {
  const latest = latestTimelineMessage(messages, message => ['user', 'agent'].includes(message.type));
  const question = parseHumanQuestion(latest?.metadata?.human_question);
  return question?.surface === surface ? question : null;
}

export function sameHumanQuestion(snapshot, raw) {
  const current = parseHumanQuestion(raw);
  return current && ['question_id', 'source_job_id', 'surface', 'project_id', 'prompt', 'expires_at']
    .every(key => current[key] === snapshot[key])
    && JSON.stringify(current.choices) === JSON.stringify(snapshot.choices) ? current : null;
}

export function humanQuestionTarget(question, context) {
  if (!question || !context) return null;
  if (question.surface === 'ide') return context.repository_id === question.project_id && !context.blocked
    && /^[a-f0-9]{64}$/.test(context.generation || '')
    ? { ide_context: { repository_id: context.repository_id, generation: context.generation } } : null;
  if (context.project_id !== question.project_id || !context.path || !context.expected_revision) return null;
  return { document_context: Object.fromEntries(['path', 'expected_revision', 'authoring_version', 'draft_digest', 'block_ids']
    .filter(key => Object.hasOwn(context, key)).map(key => [key, context[key]])) };
}

export function questionFailure(error) {
  const code = error?.response?.data?.detail?.code || error?.code;
  if (code === 'human_question_binding_changed' || code === 'source_changed') return 'Проект изменился. Проверьте его состояние или отмените этот вопрос.';
  if (code === 'human_question_not_found') return 'Вопрос недоступен. Проверьте выбранный чат и проект.';
  return 'Не удалось подтвердить состояние. Текст ответа сохранён в этой вкладке.';
}
