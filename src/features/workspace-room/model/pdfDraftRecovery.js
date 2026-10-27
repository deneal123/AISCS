/** Export only the loaded local draft, never claim it includes project assets. */
export function downloadLocalPdfDraft({ draft, file, mode }) {
  const source = mode === 'latex';
  if (source ? !file?.path || file.loading || file.truncated : !draft) return false;
  const content = source ? file.content : JSON.stringify(draft, null, 2);
  const blob = new Blob([content], { type: source ? 'text/plain;charset=utf-8' : 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  try {
    link.href = url;
    link.download = source ? file.path.split('/').pop() : 'gpthub-pdf-draft.json';
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return true;
}
