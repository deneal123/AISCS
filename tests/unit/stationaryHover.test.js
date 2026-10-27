import theme from '../../src/theme';
import { CARD_HOVER_STATE, CARD_HOVER_SOFT, GLASS_CARD_BASE } from '../../src/theme/glass';

const geometry = ['transform', 'translate', 'scale', 'width', 'height', 'padding', 'margin'];

it.each([
  ['glass card', CARD_HOVER_STATE],
  ['glass row', CARD_HOVER_SOFT],
  ...['primary', 'secondary', 'workbenchPrimary', 'workbenchSecondary'].flatMap(name =>
    ['_hover', '_active'].map(state => [name + state, theme.components.Button.variants[name][state] || {}])),
])('%s preserves the interactive hit target', (_name, state) => {
  for (const property of geometry) expect(state[property]).toBeUndefined();
});

it('animates feedback, not the button/card hit target', () => {
  for (const transition of [GLASS_CARD_BASE.transition, theme.components.Button.baseStyle.transition]) {
    expect(transition).not.toMatch(/transform|\ball\b|width|height|padding|margin/);
    expect(transition).toContain('border-color');
    expect(transition).toContain('box-shadow');
  }
  expect(CARD_HOVER_STATE.borderColor).toBeTruthy();
  expect(CARD_HOVER_STATE.boxShadow).toBeTruthy();
});
