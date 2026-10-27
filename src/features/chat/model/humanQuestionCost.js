const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const FIELDS = ['offer_id', 'state', 'estimated_credits', 'expires_at'];

/** Closed owned HTTP projection, never a browser-created approval or price. */
export function parseHumanQuestionCost(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)
    || Object.keys(raw).length !== FIELDS.length || FIELDS.some(key => !Object.hasOwn(raw, key))
    || !UUID.test(raw.offer_id || '') || raw.offer_id === '00000000-0000-0000-0000-000000000000'
    || !['pending', 'expired', 'accepted', 'declined', 'not_required', 'cancelled'].includes(raw.state)
    || !Number.isSafeInteger(raw.estimated_credits) || raw.estimated_credits < 0
    || typeof raw.expires_at !== 'string' || !Number.isFinite(Date.parse(raw.expires_at))
    || !/(Z|[+-]\d{2}:\d{2})$/.test(raw.expires_at)) throw new Error('question_cost_protocol');
  return { ...raw };
}
