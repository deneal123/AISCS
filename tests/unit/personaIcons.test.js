import { getPersonaIcon } from '../../src/features/chat/constants/personaIcons';
import { FiUser } from '../../src/shared/icons';

it('gives each built-in personality its own product-owned glyph', () => {
  const glyphs = ['engineer', 'psychologist', 'scientist', 'analyst', 'financier', 'tarot'].map(getPersonaIcon);
  expect(new Set(glyphs).size).toBe(6);
  for (const glyph of glyphs) expect(typeof glyph).toBe('function');
});

it.each(['custom-persona', '__proto__', 'constructor', undefined])('keeps an unknown ID usable: %s', id => {
  expect(getPersonaIcon(id)).toBe(FiUser);
});
