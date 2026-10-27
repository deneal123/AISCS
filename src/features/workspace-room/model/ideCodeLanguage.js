const EXTENSIONS = {
  sh: 'bash', bash: 'bash', zsh: 'bash', c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp', cs: 'csharp',
  css: 'css', diff: 'diff', patch: 'diff', go: 'go', graphql: 'graphql', gql: 'graphql',
  java: 'java', js: 'javascript', mjs: 'javascript', cjs: 'javascript', json: 'json', jsx: 'jsx',
  kt: 'kotlin', kts: 'kotlin', md: 'markdown', markdown: 'markdown', html: 'markup', htm: 'markup', xml: 'markup',
  svg: 'markup', php: 'php', py: 'python', rb: 'ruby', rs: 'rust', sql: 'sql', swift: 'swift',
  tsx: 'tsx', ts: 'typescript', yaml: 'yaml', yml: 'yaml',
};

export function ideCodeLanguage(path = '') {
  const name = path.split('/').pop().toLowerCase();
  if (name === 'dockerfile' || name.startsWith('dockerfile.')) return 'docker';
  const extension = name.split('.').pop();
  return Object.prototype.hasOwnProperty.call(EXTENSIONS, extension) ? EXTENSIONS[extension] : null;
}
