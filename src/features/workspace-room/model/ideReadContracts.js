const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const GENERATION = /^[a-f0-9]{64}$/;
const STATES = new Set(['not_created', 'dispatching', 'ready', 'pending', 'unknown', 'unavailable', 'expired', 'rejected']);
const invalid = () => { throw new Error('ide_invalid_response'); };
export const idePath = (path) => typeof path === 'string' && path.length > 0 && path.length <= 1024
  && !path.includes('\\') && [...path].every((char) => char.codePointAt(0) >= 32 && char.codePointAt(0) !== 127)
  && path.split('/').every((part) => part && part !== '.' && part !== '..' && part !== '.git' && !part.startsWith('.gpthub-'));

export function ideRepositoryPage(value, offset) {
  if (!Array.isArray(value?.items) || value.items.length > 30
    || !(value.next_offset === null || (Number.isInteger(value.next_offset) && value.next_offset > offset && value.next_offset <= 100000))) invalid();
  const seen = new Set();
  const items = value.items.map((item) => {
    if (!UUID.test(item?.repository_id) || seen.has(item.repository_id) || typeof item.name !== 'string'
      || !item.name.trim() || item.name.length > 120 || item.state !== 'registered') invalid();
    seen.add(item.repository_id);
    return { repository_id: item.repository_id, name: item.name };
  });
  return { items, nextOffset: value.next_offset };
}

export function ideRuntime(value, repositoryId) {
  const state = value?.workspace;
  if (value?.repository_id !== repositoryId || !STATES.has(state?.state)
    || typeof state?.can_retry !== 'boolean'
    || !(state.expires_at === null || (Number.isSafeInteger(state.expires_at) && state.expires_at > 0))) invalid();
  return { state: state.state, expiresAt: state.expires_at, canRetry: state.can_retry };
}

export function ideCloneRecovery(value, repositoryId) {
  if (!value || !Object.hasOwn(value, 'attempt')) invalid();
  if (value.attempt === null) return null;
  const attempt = value.attempt;
  const repository = ideRepositoryPage({ items: [attempt?.repository], next_offset: null }, 0).items[0];
  if (!UUID.test(attempt.intent_id) || !UUID.test(attempt.source_repository_id)
    || attempt.source_repository_id === repository.repository_id
    || ![repository.repository_id, attempt.source_repository_id].includes(repositoryId)
    || !['preparing', 'running', 'blocked', 'complete', 'failed', 'unconfirmed'].includes(attempt.state)) invalid();
  const request = attempt.request;
  if (request !== null) {
    if (typeof request?.origin !== 'string' || !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\.git$/.test(request.origin)
      || request.origin.length > 512 || typeof request.branch !== 'string' || request.branch.length > 200
      || (request.branch && (!/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(request.branch) || request.branch.includes('..')
        || request.branch.split('/').some(part => !part || part.startsWith('.') || part.endsWith('.lock') || part.endsWith('.'))))) invalid();
    const parts = request.origin.slice('https://github.com/'.length).split('/');
    parts[1] = parts[1].slice(0, -4);
    if (parts.some(part => !part || part === '.' || part === '..' || part.startsWith('-'))) invalid();
  }
  return { repository: { ...repository, state: 'registered' }, intent_id: attempt.intent_id,
    source_repository_id: attempt.source_repository_id, state: attempt.state,
    request: request === null ? null : { origin: request.origin, branch: request.branch } };
}

export function idePreparation(value, repositoryId = '') {
  const item = ideRepositoryPage({ items: [value?.repository], next_offset: null }, 0).items[0];
  if (repositoryId && item.repository_id !== repositoryId) invalid();
  const runtime = ideRuntime(value.runtime, item.repository_id);
  if (value.git !== null && (typeof value.git?.initialized !== 'boolean'
    || !(value.git.branch === null || (typeof value.git.branch === 'string' && value.git.branch.length <= 200)))) invalid();
  if (value.git_error !== undefined && (typeof value.git_error !== 'string' || value.git_error.length > 64)) invalid();
  return { repository: { ...item, state: 'registered' }, runtime, gitWarning: Boolean(value.git_error) };
}

export function ideTree(value, repositoryId) {
  if (value?.repository_id !== repositoryId || !GENERATION.test(value.generation)
    || !Array.isArray(value.entries) || value.entries.length > 400 || typeof value.truncated !== 'boolean') invalid();
  const seen = new Set();
  const entries = value.entries.map((item) => {
    if (!idePath(item?.path) || seen.has(item.path) || !['file', 'dir'].includes(item.type)
      || !Number.isSafeInteger(item.size) || item.size < 0 || typeof item.incomplete !== 'boolean') invalid();
    seen.add(item.path);
    return { path: item.path, type: item.type, size: item.size, incomplete: item.incomplete };
  });
  return { entries, generation: value.generation, truncated: value.truncated };
}

export function ideFile(value, repositoryId, path, generation) {
  if (value?.repository_id !== repositoryId || value.generation !== generation || value.path !== path
    || !['text', 'binary'].includes(value.kind) || !Number.isSafeInteger(value.size) || value.size < 0
    || typeof value.truncated !== 'boolean') invalid();
  if (value.kind === 'text' ? (typeof value.content !== 'string' || value.content.length > 262144
    || (value.truncated ? value.digest !== null : !GENERATION.test(value.digest)))
    : value.content !== null || value.digest !== null) invalid();
  return { path, kind: value.kind, content: value.content, truncated: value.truncated, size: value.size, digest: value.digest };
}

export function ideWrite(value, repositoryId, path, generation, operation, maxBytes = 262144) {
  if (value?.repository_id !== repositoryId || value.generation !== generation || value.path !== path || value.written !== true
    || value.kind !== (operation === 'directory' ? 'dir' : 'file') || !Number.isSafeInteger(value.size) || value.size < 0
    || (operation === 'directory' ? value.digest !== null || value.size !== 0 : !GENERATION.test(value.digest) || value.size > maxBytes)) invalid();
  return value;
}

export const ideLibraryReceipt = (value, repositoryId, path, generation) =>
  ideWrite(value, repositoryId, path, generation, 'file', 20 * 1024 * 1024);

export function ideMove(value, repositoryId, path, destination, generation) {
  if (value?.repository_id !== repositoryId || value.generation !== generation || value.moved_from !== path
    || value.path !== destination || value.moved !== true || !idePath(destination)
    || !Number.isSafeInteger(value.size) || value.size < 0) invalid();
  return { repository_id: repositoryId, generation, path: destination, moved_from: path, moved: true, size: value.size };
}

export const IDE_RUNTIME_LABELS = Object.freeze({
  not_created: 'Среда не запущена', dispatching: 'Запуск запрошен', ready: 'Среда доступна',
  pending: 'Среда запускается', unknown: 'Состояние среды не подтверждено',
  unavailable: 'Среда недоступна', expired: 'Срок среды истёк', rejected: 'Запуск отклонён',
});
