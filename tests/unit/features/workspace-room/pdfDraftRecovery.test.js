import { downloadLocalPdfDraft } from '@features/workspace-room/model/pdfDraftRecovery';

let create, revoke, click, blob;
beforeEach(() => {
  jest.useFakeTimers();
  create = URL.createObjectURL; revoke = URL.revokeObjectURL;
  URL.createObjectURL = jest.fn(() => 'blob:local-draft');
  URL.revokeObjectURL = jest.fn();
  click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const NativeBlob = Blob;
  blob = jest.spyOn(global, 'Blob').mockImplementation((content, options) => new NativeBlob(content, options));
});
afterEach(() => {
  jest.runOnlyPendingTimers(); jest.useRealTimers();
  blob.mockRestore(); click.mockRestore();
  URL.createObjectURL = create; URL.revokeObjectURL = revoke;
});

it('exports the exact local structured text without a network request or attached assets', () => {
  const draft = { title: 'Локальный текст', blocks: [{ kind: 'table', rows: [['', '2']] }] };
  expect(downloadLocalPdfDraft({ draft, mode: 'content' })).toBe(true);
  expect(blob).toHaveBeenCalledWith([JSON.stringify(draft, null, 2)], { type: 'application/json;charset=utf-8' });
  expect(click).toHaveBeenCalledTimes(1);
  expect(document.querySelector('a[download]')).toBeNull();
  jest.runOnlyPendingTimers();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:local-draft');
});

it('exports the edited raw source, never a server baseline or a truncated file', () => {
  const file = { path: 'documents/a/content/local.tex', content: 'my unsaved source', original: 'old' };
  expect(downloadLocalPdfDraft({ file, mode: 'latex' })).toBe(true);
  expect(blob).toHaveBeenCalledWith(['my unsaved source'], { type: 'text/plain;charset=utf-8' });
  expect(downloadLocalPdfDraft({ file: { ...file, truncated: true }, mode: 'latex' })).toBe(false);
  expect(click).toHaveBeenCalledTimes(1);
});
