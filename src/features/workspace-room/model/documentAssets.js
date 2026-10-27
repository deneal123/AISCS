/** Snapshot paths are workspace-relative; TeX references are project-relative. */
export const isPdfImageName = (name) => typeof name === 'string' && /\.(png|jpe?g|pdf)$/i.test(name);
const ASSET = /^figures\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_.-]+\.(?:pdf|png|jpe?g|eps)$/i;

export function projectImageOptions(entries = [], path, library = []) {
  if (!path) return [];
  const prefix = `${path}/`;
  const seen = new Set();
  return entries.flatMap((entry) => {
    if (entry?.type !== 'file' || typeof entry.path !== 'string' || !entry.path.startsWith(prefix)) return [];
    const asset = entry.path.slice(prefix.length);
    if (asset.length > 500 || !ASSET.test(asset) || asset.split('/').includes('..') || seen.has(asset)) return [];
    seen.add(asset);
    const libraryId = /^figures\/library_([a-f0-9]{32})\./.exec(asset)?.[1];
    const original = libraryId && library.find((item) => typeof item.file_id === 'string' && item.file_id.replaceAll('-', '') === libraryId);
    return [{ value: asset, label: typeof original?.name === 'string' && original.name ? original.name : asset.slice('figures/'.length) }];
  });
}
