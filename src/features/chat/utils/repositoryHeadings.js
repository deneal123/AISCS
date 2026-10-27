/** Local README anchors only: no user-controlled global DOM identifiers. */
function pushChildren(pending, node) {
  const children = node.children || [];
  for (let index = children.length - 1; index >= 0; index -= 1) pending.push(children[index]);
}

function textOf(root) {
  const pending = [root];
  const text = [];
  while (pending.length) {
    const node = pending.pop();
    if (node.type === 'text') text.push(node.value);
    else pushChildren(pending, node);
  }
  return text.join('');
}

export default function repositoryHeadings({ prefix }) {
  return (tree) => {
    const used = new Set();
    const suffixes = new Map();
    const pending = [tree];
    while (pending.length) {
      const node = pending.pop();
      if (node.type === 'element' && /^h[1-6]$/.test(node.tagName)) {
        const base = textOf(node).normalize('NFC').toLowerCase().trim()
          .replace(/[^\p{L}\p{N}\p{M}_ -]/gu, '').replace(/ /g, '-') || 'section';
        let slug = base;
        let suffix = suffixes.get(base) || 0;
        while (used.has(slug)) slug = `${base}-${++suffix}`;
        suffixes.set(base, suffix);
        used.add(slug);
        node.properties = { ...node.properties, id: `${prefix}${slug}`,
          'data-repository-anchor': slug, tabIndex: -1 };
      }
      pushChildren(pending, node);
    }
  };
}
