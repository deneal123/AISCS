// Per-tab receipt for resuming the second stage of one submitted simulation.
// The backend remains the source of truth; a bounded per-tab draft signature
// only allows a failed calculation to be retried when the draft is unchanged.
const prefix = 'simulation:pending-feedback:';
const selectedPrefix = 'simulation:selected-feedback-source:';
const retryDraftPrefix = 'simulation:feedback-retry-draft:';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function key(sceneId) {
  return typeof sceneId === 'string' && uuid.test(sceneId) ? `${prefix}${sceneId}` : null;
}

function valid(receipt) {
  return receipt && typeof receipt === 'object' && receipt.version === 1
    && typeof receipt.sourceId === 'string' && uuid.test(receipt.sourceId)
    && typeof receipt.requestId === 'string' && uuid.test(receipt.requestId)
    && (receipt.retry === undefined || receipt.retry === true);
}

export function readPendingFeedback(storage, sceneId) {
  const name = key(sceneId);
  if (!storage || !name) return null;
  try {
    const receipt = JSON.parse(storage.getItem(name));
    return valid(receipt) ? { version: 1, sourceId: receipt.sourceId, requestId: receipt.requestId,
      ...(receipt.retry ? { retry: true } : {}) } : null;
  } catch { return null; }
}

export function writePendingFeedback(storage, sceneId, receipt) {
  const name = key(sceneId);
  if (!storage || !name || !valid(receipt)) return false;
  try {
    storage.setItem(name, JSON.stringify({ version: 1, sourceId: receipt.sourceId, requestId: receipt.requestId,
      ...(receipt.retry ? { retry: true } : {}) }));
    return true;
  } catch { return false; }
}

export function clearPendingFeedback(storage, sceneId, sourceId) {
  const name = key(sceneId);
  if (!name || readPendingFeedback(storage, sceneId)?.sourceId !== sourceId) return false;
  try { storage.removeItem(name); return true; } catch { return false; }
}

export function readSelectedFeedbackSource(storage, sceneId) {
  if (!storage || !key(sceneId)) return null;
  try {
    const sourceId = storage.getItem(`${selectedPrefix}${sceneId}`);
    return typeof sourceId === 'string' && uuid.test(sourceId) ? sourceId : null;
  } catch { return null; }
}

export function writeSelectedFeedbackSource(storage, sceneId, sourceId) {
  if (!storage || !key(sceneId) || typeof sourceId !== 'string' || !uuid.test(sourceId)) return false;
  try { storage.setItem(`${selectedPrefix}${sceneId}`, sourceId); return true; }
  catch { return false; }
}

export function readFeedbackRetryDraft(storage, sceneId) {
  if (!storage || !key(sceneId)) return null;
  try {
    const value = JSON.parse(storage.getItem(`${retryDraftPrefix}${sceneId}`));
    if (value?.version !== 1 || typeof value.sourceId !== 'string' || !uuid.test(value.sourceId)
        || typeof value.signature !== 'string' || !value.signature.length || value.signature.length > 10000) return null;
    return { sourceId: value.sourceId, signature: value.signature };
  } catch { return null; }
}

export function writeFeedbackRetryDraft(storage, sceneId, draft) {
  if (!storage || !key(sceneId) || typeof draft?.sourceId !== 'string' || !uuid.test(draft.sourceId)
      || typeof draft.signature !== 'string' || !draft.signature.length || draft.signature.length > 10000) return false;
  try {
    storage.setItem(`${retryDraftPrefix}${sceneId}`, JSON.stringify({
      version: 1, sourceId: draft.sourceId, signature: draft.signature,
    }));
    return true;
  } catch { return false; }
}
