import { ideDraftComparison, ideReviewedConflict } from '@features/workspace-room/model/ideDraftComparison';

it('separates local edits from external changes without a write or commit claim', () => {
  const file = { path: 'a.py', original: 'head\nold\ntail', content: 'head\nmine\ntail' };
  const text = ideDraftComparison(file, 'head\ntheirs\ntail');
  expect(text).toContain('Основа → ваш черновик');
  expect(text).toContain('Основа → файл в среде');
  expect(text).toContain('Со строки 2; −1 / +1');
  expect(text).toContain('+ mine');
  expect(text).toContain('+ theirs');
});

it('bounds huge changes and very long lines with visible omission labels', () => {
  const text = ideDraftComparison({ original: 'a\n'.repeat(10000), content: 'b'.repeat(20000) }, 'c\n'.repeat(10000));
  expect(text.length).toBeLessThan(12100);
  expect(text).toContain('строка сокращена');
  expect(text).toContain('строки пропущены');
});

it('detects equality without implying that the lost operation succeeded', () => {
  const file = { path: 'a.py', original: 'old', content: 'mine' };
  const result = ideReviewedConflict(file, { kind: 'text', content: 'mine', truncated: false }, 'generation');
  expect(result.actualContent).toBe('mine');
  expect(result.notice).toContain('совпадает');
  expect(result.notice).not.toContain('подтверждена');
});

it.each([{ kind: 'binary', content: null, truncated: false }, { kind: 'text', content: 'preview', truncated: true }])('never enables replacement from a partial or binary read', actual => {
  const result = ideReviewedConflict({ path: 'a.py', content: 'draft' }, actual, 'generation');
  expect(result.actualContent).toBeNull();
  expect(result.diff).toBe('');
});
