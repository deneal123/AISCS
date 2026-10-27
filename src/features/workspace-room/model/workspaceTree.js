const collator = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' });

/** Presentation of the existing snapshot, never a filesystem read or mutation. */
export function buildWorkspaceTree(entries, basePath = '') {
  const root = { children: new Map() };
  for (const entry of entries) {
    if (typeof entry.path !== 'string' || !['file', 'dir', 'directory'].includes(entry.type)) continue;
    const relative = basePath ? (entry.path.startsWith(`${basePath}/`) ? entry.path.slice(basePath.length + 1) : '') : entry.path;
    const parts = relative.split('/');
    if (!relative || parts.some((part) => !part || part === '.' || part === '..')) continue;
    let parent = root;
    for (let index = 0; index < parts.length; index += 1) {
      const name = parts[index];
      const path = [basePath, ...parts.slice(0, index + 1)].filter(Boolean).join('/');
      let node = parent.children.get(name);
      if (!node) {
        node = { name, path, type: 'directory', children: new Map() };
        parent.children.set(name, node);
      }
      if (index === parts.length - 1) Object.assign(node, entry, { name, path, type: entry.type === 'file' ? 'file' : 'directory' });
      parent = node;
    }
  }
  const sort = (parent) => [...parent.children.values()]
    .sort((a, b) => Number(b.type === 'directory') - Number(a.type === 'directory') || collator.compare(a.name, b.name))
    .map((node) => ({ ...node, children: sort(node) }));
  return sort(root);
}

export function workspaceAncestors(path, basePath = '') {
  if (!path || (basePath && !path.startsWith(`${basePath}/`))) return [];
  const parts = path.split('/');
  const ancestors = [];
  for (let index = 1; index < parts.length; index += 1) {
    const parent = parts.slice(0, index).join('/');
    if (!basePath || parent.startsWith(`${basePath}/`)) ancestors.push(parent);
  }
  return ancestors;
}
