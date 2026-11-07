// Per-tab receipt for resuming the second stage of one submitted simulation.
// Only opaque identifiers are stored; the backend remains the source of truth.
const prefix = 'simulation:pending-feedback:';
const selectedPrefix = 'simulation:selected-feedback-source:';
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
