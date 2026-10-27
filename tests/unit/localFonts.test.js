const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const publicRoot = path.join(__dirname, '../../public');
const fontDir = path.join(publicRoot, 'static/fonts/fontsource-5.3.0');
const manifest = JSON.parse(fs.readFileSync(path.join(fontDir, 'manifest.json'), 'utf8'));

it('ships pinned genuine WOFF2 subsets and their original redistribution licenses', () => {
  expect(Object.keys(manifest.files)).toHaveLength(4);
  for (const [name, hash] of Object.entries(manifest.files)) {
    const bytes = fs.readFileSync(path.join(fontDir, name));
    expect(bytes.toString('ascii', 0, 4)).toBe('wOF2');
    expect(bytes.readUInt32BE(8)).toBe(bytes.length);
    expect(crypto.createHash('sha256').update(bytes).digest('hex')).toBe(hash);
  }
  for (const family of ['inter', 'jetbrains-mono']) {
    expect(fs.readFileSync(path.join(fontDir, `${family}-LICENSE.txt`), 'utf8'))
      .toContain('SIL OPEN FONT LICENSE Version 1.1');
  }
});

it('подключает локальный CSS без принудительной загрузки неиспользуемых шрифтов', () => {
  const html = fs.readFileSync(path.join(publicRoot, 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(fontDir, 'fonts.css'), 'utf8');
  expect(html).not.toMatch(/fonts\.googleapis|fonts\.gstatic|media="print"/);
  expect(html).not.toMatch(/<link\b(?=[^>]*\brel="preload")(?=[^>]*\bas="font")[^>]*>/);
  expect(html).toContain('href="%PUBLIC_URL%/static/fonts/fontsource-5.3.0/fonts.css"');
  expect(css.match(/font-display: optional;/g)).toHaveLength(4);
  for (const name of Object.keys(manifest.files)) expect(css).toContain(`url('./${name}')`);
  expect(css).toContain('font-weight: 100 800;');
  expect(css).toContain('font-weight: 100 900;');
});
