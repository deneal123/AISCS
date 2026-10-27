const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const GENERATION = /^[a-f0-9]{64}$/;
const STATES = new Set(['pending', 'published', 'retired', 'conflict']);
const invalid = () => { throw new Error('ide_checkpoint_response'); };
const bytes = value => Number.isSafeInteger(value) && value >= 0;

export function checkpointResult(value, repositoryId, checkpointId) {
  if (value?.repository_id !== repositoryId || !UUID.test(value.checkpoint_id) || !STATES.has(value.state)
    || (checkpointId && value.checkpoint_id !== checkpointId)
    || typeof value.is_current !== 'boolean' || !bytes(value.size_bytes)
    || (value.can_discard !== undefined && typeof value.can_discard !== 'boolean')
    || (value.collected !== undefined && typeof value.collected !== 'boolean')
    || (value.collected && !['retired', 'conflict'].includes(value.state))
    || (value.can_abandon !== undefined && typeof value.can_abandon !== 'boolean')
    || (value.can_abandon && (value.state !== 'pending' || value.is_current || value.collected))
    || (value.can_discard && (value.state === 'published' || value.is_current || value.collected))) invalid();
  return { checkpoint_id: value.checkpoint_id, state: value.state, is_current: value.is_current, size_bytes: value.size_bytes,
    can_discard: value.can_discard === true, collected: value.collected === true, can_abandon: value.can_abandon === true };
}

export function restoreResult(value, repositoryId) {
  if (value?.repository_id !== repositoryId || !UUID.test(value.restore_id) || !UUID.test(value.checkpoint_id)
    || !['pending', 'published', 'conflict', 'expired'].includes(value.state)
    || typeof value.active !== 'boolean' || (value.active && (value.state !== 'published' || !GENERATION.test(value.generation)))) invalid();
  return { restore_id: value.restore_id, checkpoint_id: value.checkpoint_id, state: value.state, active: value.active };
}

export function checkpointHistory(value, repositoryId) {
  if (value?.repository_id !== repositoryId || !Array.isArray(value.items) || value.items.length > 32
    || typeof value.truncated !== 'boolean' || !bytes(value.usage?.used_bytes)
    || !bytes(value.usage?.max_bytes) || !bytes(value.usage?.max_snapshot_bytes)
    || !(value.runtime?.generation === null || GENERATION.test(value.runtime?.generation))
    || !['not_created', 'dispatching', 'ready', 'pending', 'unknown', 'unavailable', 'expired', 'rejected'].includes(value.runtime?.state)) invalid();
  const seen = new Set();
  const items = value.items.map(item => {
    if (!UUID.test(item?.checkpoint_id) || seen.has(item.checkpoint_id) || !STATES.has(item.state)
      || !bytes(item.size_bytes) || typeof item.is_current !== 'boolean'
      || (item.can_discard !== undefined && typeof item.can_discard !== 'boolean')
      || (item.can_abandon !== undefined && typeof item.can_abandon !== 'boolean')
      || (item.can_abandon && (item.state !== 'pending' || item.is_current))
      || (item.can_discard && (item.state === 'published' || item.is_current))
      || !Number.isFinite(Date.parse(item.created_at))) invalid();
    seen.add(item.checkpoint_id);
    return { checkpoint_id: item.checkpoint_id, state: item.state, is_current: item.is_current,
      size_bytes: item.size_bytes, created_at: item.created_at, can_discard: item.can_discard === true, can_abandon: item.can_abandon === true };
  });
  return { items, truncated: value.truncated,
    usage: { used_bytes: value.usage.used_bytes, max_bytes: value.usage.max_bytes },
    runtime: { generation: value.runtime.generation, state: value.runtime.state },
    last_restore: value.last_restore == null ? null : restoreResult(value.last_restore, repositoryId) };
}

// Only opaque operation identity lives in session storage, never code or credentials.
export function savedProjectIntent(value) {
  if (!value || !UUID.test(value.checkpoint_id)) return null;
  if (value.kind === 'save' && GENERATION.test(value.generation)
    && (value.base_checkpoint_id === null || UUID.test(value.base_checkpoint_id))) return {
    kind: 'save', checkpoint_id: value.checkpoint_id, generation: value.generation, base_checkpoint_id: value.base_checkpoint_id,
  };
  if (value.kind === 'restore' && UUID.test(value.restore_id) && GENERATION.test(value.base_generation)) return {
    kind: 'restore', checkpoint_id: value.checkpoint_id, restore_id: value.restore_id, base_generation: value.base_generation,
  };
  return null;
}
