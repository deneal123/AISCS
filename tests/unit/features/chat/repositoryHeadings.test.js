import repositoryHeadings from '@features/chat/utils/repositoryHeadings';

const heading = value => ({ type: 'element', tagName: 'h2', children: [{ type: 'text', value }] });

it('assigns scoped Unicode IDs, preserving collision order and inline text', () => {
  const tree = { children: [heading('Раздел!'), heading('Раздел-1'), heading('Раздел!'),
    { type: 'element', tagName: 'h3', children: [{ type: 'element', tagName: 'code', children: [{ type: 'text', value: 'API' }] }, { type: 'text', value: ' Setup' }] }] };
  repositoryHeadings({ prefix: 'local-' })(tree);
  expect(tree.children.map(node => node.properties['data-repository-anchor']))
    .toEqual(['раздел', 'раздел-1', 'раздел-2', 'api-setup']);
  expect(tree.children.every(node => node.properties.id.startsWith('local-'))).toBe(true);
});

it('keeps repeated heading numbering monotonic without restarting a quadratic scan', () => {
  const tree = { children: Array.from({ length: 5000 }, () => heading('Same')) };
  repositoryHeadings({ prefix: 'local-' })(tree);
  expect(tree.children[0].properties.id).toBe('local-same');
  expect(tree.children.at(-1).properties.id).toBe('local-same-4999');
});
