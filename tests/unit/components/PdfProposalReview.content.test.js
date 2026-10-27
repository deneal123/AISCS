import { proposalBlockText } from '@features/workspace-room/components/PdfProposalReview';
import { proposalChanges, validProposal } from '@features/workspace-room/model/pdfProposal';

it('shows actual table changes even when both versions have a caption', () => {
  expect(proposalBlockText({ title: 'Результаты', columns: ['Метод', 'Значение'], rows: [['A', '2']] }))
    .toBe('Результаты\n\nМетод | Значение\nA | 2');
});

it.each(['title', 'version', 'remove', 'reorder', 'kind', 'object_source', 'unknown_field'])('rejects hidden or unsupported %s changes', (type) => {
  const before = { title: 'Обзор', version: 1, blocks: [
    { block_id: 'one', kind: 'paragraph', text: 'Один' }, { block_id: 'two', kind: 'citation', source_id: 1 },
  ] };
  const draft = JSON.parse(JSON.stringify(before));
  if (type === 'title') draft.title = 'Другой заголовок';
  if (type === 'version') draft.version = 2;
  if (type === 'remove') draft.blocks.pop();
  if (type === 'reorder') draft.blocks.reverse();
  if (type === 'kind') draft.blocks[0].kind = 'constructor';
  if (type === 'object_source') draft.blocks[1].source_id = {};
  if (type === 'unknown_field') draft.blocks[0].unreviewed = 'Изменение';
  expect(validProposal({ path: 'documents/a', proposal_id: 'proposal', stale: false,
    expected_revision: 'r1', authoring_version: 1, draft_digest: 'a'.repeat(64), before, draft }, 'documents/a', 'proposal')).toBe(false);
});

it('does not invent a change from JSON key order, while retaining ordered list differences', () => {
  const before = { block_id: 'list', kind: 'list', items: ['A', 'B'] };
  expect(proposalChanges({ before: { blocks: [before] }, draft: { blocks: [{ items: ['A', 'B'], kind: 'list', block_id: 'list' }] } })).toEqual([]);
  expect(proposalChanges({ before: { blocks: [before] }, draft: { blocks: [{ ...before, items: ['B', 'A'] }] } })).toHaveLength(1);
});

it('does not hide list, figure or citation changes behind a title', () => {
  expect(proposalBlockText({ title: 'Иллюстрация', text: 'Подпись', items: ['Тезис'], asset_path: 'figures/chart.png', source_id: 5 }))
    .toContain('Изображение: figures/chart.png');
  expect(proposalBlockText({ title: 'Тезисы', items: ['Первый', 'Второй'] })).toContain('Первый\n• Второй');
  expect(proposalBlockText({ source_id: 5 })).toBe('Источник: 5');
});

const structure = (blocks) => {
  const before = { title: 'Котики', version: 1, blocks: [
    { block_id: 'one', kind: 'slide', text: 'Первый' },
    { block_id: 'two', kind: 'slide', text: 'Второй' },
    { block_id: 'three', kind: 'slide', text: 'Третий' },
  ] };
  return { patch_version: 2, path: 'documents/a', proposal_id: 'proposal', stale: false,
    expected_revision: 'r1', authoring_version: 1, draft_digest: 'a'.repeat(64),
    before, draft: { ...before, blocks } };
};

it('reviews every v2 insertion, deletion and changed relative order', () => {
  const value = structure([
    { block_id: 'three', kind: 'slide', text: 'Третий' },
    { block_id: 'one', kind: 'slide', text: 'Изменённый первый' },
    { block_id: 'new_cat', kind: 'slide', text: 'Новый' },
  ]);
  expect(validProposal(value, 'documents/a', 'proposal')).toBe(true);
  expect(proposalChanges(value).map((change) => change.kind)).toEqual(['move', 'replace_move', 'insert', 'delete']);
  expect(proposalChanges(value).find((change) => change.kind === 'delete').before.block_id).toBe('two');
});

it('does not invent moves when only inserting or deleting adjacent blocks', () => {
  const value = structure([]);
  value.draft.blocks = [{ block_id: 'new_cat', kind: 'slide', text: 'Новый' }, ...value.before.blocks];
  expect(proposalChanges(value).map((change) => change.kind)).toEqual(['insert']);
  value.draft.blocks = value.before.blocks.filter((block) => block.block_id !== 'two');
  expect(proposalChanges(value).map((change) => change.kind)).toEqual(['delete']);
});

it.each(['version', 'duplicate', 'new_id', 'kind', 'empty'])('rejects invalid v2 %s without losing legacy strictness', (type) => {
  const value = structure([{ block_id: 'new_cat', kind: 'slide' }]);
  if (type === 'version') value.patch_version = 3;
  if (type === 'duplicate') value.draft.blocks.push(value.draft.blocks[0]);
  if (type === 'new_id') value.draft.blocks[0].block_id = 'invented';
  if (type === 'kind') value.draft.blocks = [{ ...value.before.blocks[0], kind: 'paragraph' }];
  if (type === 'empty') value.draft.blocks = [];
  expect(validProposal(value, 'documents/a', 'proposal')).toBe(false);
});
