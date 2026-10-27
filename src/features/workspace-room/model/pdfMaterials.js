const SERVICE_FILE = /^(?:\.[^/]+|document\.toml|gpthub-core\.sty)$|\.(?:sty|cls|bst|cfg)$/i;

/** Presentation only: no paths are removed from the available material set. */
export function groupPdfMaterials(entries, projectPath) {
  const groups = { sources: [], service: [], builds: [], shared: [] };
  for (const item of entries || []) {
    if (projectPath && item.path?.startsWith(`${projectPath}/`)) {
      const relative = item.path.slice(projectPath.length + 1);
      const key = relative === 'artifacts' || relative.startsWith('artifacts/') ? 'builds'
        : SERVICE_FILE.test(relative.split('/')[0]) ? 'service' : 'sources';
      groups[key].push(item);
    } else if (item.path !== 'documents' && !item.path?.startsWith('documents/')) groups.shared.push(item);
  }
  return groups;
}

export const materialCount = items => items.filter(item => item.type === 'file').length;
