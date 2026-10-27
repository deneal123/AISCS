import { isPdfImageName, projectImageOptions } from '@features/workspace-room/model/documentAssets';

it('lists only existing renderer-compatible figures under the exact project boundary', () => {
  const names = ['documents/paper/figures/chart.png', 'documents/paper/figures/chart.png',
    'documents/paper-two/figures/other.png', 'documents/other/figures/other.pdf', 'figures/root.png',
    'documents/paper/figures/../secret.png', 'documents/paper/figures/chart.webp', 'documents/paper/assets/other.png'];
  const entries = names.map((path) => ({ type: 'file', path }));
  entries.push({ type: 'dir', path: 'documents/paper/figures/folder.png' });
  expect(projectImageOptions(entries, 'documents/paper')).toEqual([{ value: 'figures/chart.png', label: 'chart.png' }]);
  expect(projectImageOptions(entries, null)).toEqual([]);
});

it.each(['chart.PNG', 'chart.jpg', 'chart.jpeg', 'figure.pdf'])('accepts supported Library material %s', (name) => {
  expect(isPdfImageName(name)).toBe(true);
});

it('uses the owned Library filename for a server-assigned asset without changing its TeX reference', () => {
  const path = 'documents/paper/figures/library_12345678123412341234123456789abc.png';
  expect(projectImageOptions([{ type: 'file', path }], 'documents/paper',
    [{ file_id: '12345678-1234-1234-1234-123456789abc', name: 'Диаграмма.png' }]))
    .toEqual([{ value: 'figures/library_12345678123412341234123456789abc.png', label: 'Диаграмма.png' }]);
});
it.each(['chart.svg', 'chart.webp', 'notes.tex', undefined])('does not advertise unsupported figure %s', (name) => {
  expect(isPdfImageName(name)).toBe(false);
});
