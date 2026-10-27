import fs from 'fs';
import path from 'path';
import { colors } from '../../src/theme/tokens';
import theme from '../../src/theme';

it('keeps enabled button opacity immediate while retaining colour feedback', () => {
  const transition = theme.components.Button.baseStyle.transition;
  expect(transition).not.toMatch(/(^|,)\s*(opacity|all)\b/);
  expect(transition).toContain('background-color');
  expect(transition).toContain('box-shadow');
});

it('keeps tooltip surfaces opaque without a competing background shorthand', () => {
  expect(theme.components.Tooltip.baseStyle.bg).toBe(colors.bg.menu);
  expect(theme.components.Tooltip.baseStyle.background).toBeUndefined();
});

it('uses defined numeric palette entries in composer and its shared picker owners', () => {
  const sourceRoot = path.join(__dirname, '../../src');
  const composer = 'features/chat/components/composer';
  const files = fs.readdirSync(path.join(sourceRoot, composer))
    .filter((name) => name.endsWith('.jsx')).map((name) => `${composer}/${name}`)
    .concat(['shared/controls/ChoicePanel.jsx', 'shared/controls/AppSelect.jsx',
      'features/chat/components/ModelSelector.jsx']);
  let checked = 0;
  for (const file of files) {
    const source = fs.readFileSync(path.join(sourceRoot, file), 'utf8');
    for (const [, ramp, key] of source.matchAll(/colors\.(\w+)\[(\d+)\]/g)) {
      expect({ file, token: `${ramp}.${key}`, defined: typeof colors[ramp]?.[key] === 'string' })
        .toEqual({ file, token: `${ramp}.${key}`, defined: true });
      checked += 1;
    }
  }
  expect(checked).toBeGreaterThan(20);
});
