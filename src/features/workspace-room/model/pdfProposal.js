const BLOCK_NAMES = {
  section: 'Заголовок', paragraph: 'Абзац', list: 'Список', table: 'Таблица',
  figure: 'Изображение', equation: 'Формула', callout: 'Выноска', slide: 'Слайд',
  signature: 'Подписи', citation: 'Цитирование',
};
const BLOCK_FIELDS = new Set(['block_id', 'kind', 'title', 'text', 'items', 'columns', 'rows', 'source_id', 'asset_path', 'level']);

const stable = (value) => JSON.stringify(value, (_, item) => (
  item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item
));

export const proposalBlockName = (block = {}) => Object.hasOwn(BLOCK_NAMES, block.kind)
  ? BLOCK_NAMES[block.kind] : 'Фрагмент документа';

export function proposalBlockText(block = {}) {
  const parts = [block.title, block.text];
  if (block.items?.length) parts.push(block.items.map((item) => `• ${item}`).join('\n'));
  if (block.columns?.length) parts.push([block.columns, ...(block.rows || [])].map((row) => row.join(' | ')).join('\n'));
  if (block.asset_path) parts.push(`Изображение: ${block.asset_path}`);
  if (block.source_id != null) parts.push(`Источник: ${block.source_id}`);
  return parts.filter(Boolean).join('\n\n') || 'Пустой блок';
}

const validBlock = (block) => block && typeof block === 'object'
  && Object.keys(block).every((key) => BLOCK_FIELDS.has(key))
  && typeof block.block_id === 'string' && /^[a-z][a-z0-9_-]{2,63}$/.test(block.block_id) && Object.hasOwn(BLOCK_NAMES, block.kind)
  && (block.source_id == null || (Number.isInteger(block.source_id) && block.source_id >= 1 && block.source_id <= 10000))
  && (block.level == null || (Number.isInteger(block.level) && block.level >= 1 && block.level <= 3))
  && ['title', 'text', 'asset_path'].every((key) => block[key] == null || typeof block[key] === 'string')
  && ['items', 'columns'].every((key) => block[key] == null
    || (Array.isArray(block[key]) && block[key].every((item) => typeof item === 'string')))
  && (block.rows == null || (Array.isArray(block.rows)
    && block.rows.every((row) => Array.isArray(row) && row.every((cell) => typeof cell === 'string'))));

/** Validate the read projection, not authorization: the server still fences apply. */
export function validProposal(value, path, proposalId) {
  const before = value?.before?.blocks;
  const after = value?.draft?.blocks;
  const version = value?.patch_version === undefined ? 1 : value.patch_version;
  const valid = value?.path === path && value.proposal_id === proposalId && typeof value.stale === 'boolean'
    && typeof value.expected_revision === 'string' && Boolean(value.expected_revision)
    && Number.isInteger(value.authoring_version) && value.authoring_version > 0
    && /^[a-f0-9]{64}$/i.test(value.draft_digest || '')
    && typeof value.before?.title === 'string'
    && stable({ ...value.before, blocks: null }) === stable({ ...value.draft, blocks: null })
    && Array.isArray(before) && before.length > 0 && before.length <= 120
    && Array.isArray(after) && after.length > 0 && after.length <= 120
    && new Set(before.map((block) => block?.block_id)).size === before.length
    && new Set(after.map((block) => block?.block_id)).size === after.length
    && before.every(validBlock) && after.every(validBlock);
  if (!valid) return false;
  if (version === 1) return after.length === before.length
    && before.every((block, index) => block.block_id === after[index].block_id && block.kind === after[index].kind);
  if (version !== 2) return false;
  const existing = new Map(before.map((block) => [block.block_id, block]));
  return after.every((block) => existing.has(block.block_id)
    ? existing.get(block.block_id).kind === block.kind : /^new_[a-z0-9_-]+$/.test(block.block_id));
}

export function proposalChanges(value) {
  if (!value?.before?.blocks || !value?.draft?.blocks) return [];
  if (value.patch_version === 2) return structuralChanges(value.before.blocks, value.draft.blocks);
  return value.draft.blocks.flatMap((block, index) => {
    const before = value.before.blocks[index];
    return stable(block) === stable(before) ? [] : [{ before, after: block, index }];
  });
}

function structuralChanges(before, after) {
  const existing = new Map(before.map((block, index) => [block.block_id, { block, index }]));
  const next = new Set(after.map((block) => block.block_id));
  const oldOrder = before.filter((block) => next.has(block.block_id)).map((block) => block.block_id);
  const newOrder = after.filter((block) => existing.has(block.block_id)).map((block) => block.block_id);
  const changes = after.flatMap((block, index) => {
    const prior = existing.get(block.block_id);
    if (!prior) return [{ before: null, after: block, index, kind: 'insert', toIndex: index }];
    const moved = oldOrder.indexOf(block.block_id) !== newOrder.indexOf(block.block_id);
    const edited = stable(block) !== stable(prior.block);
    if (!moved && !edited) return [];
    return [{ before: prior.block, after: block, index, fromIndex: prior.index, toIndex: index,
      kind: moved ? (edited ? 'replace_move' : 'move') : 'replace' }];
  });
  return [...changes, ...before.flatMap((block, index) => next.has(block.block_id)
    ? [] : [{ before: block, after: null, index, fromIndex: index, kind: 'delete' }])];
}
