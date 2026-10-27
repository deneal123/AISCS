import { colors, typography } from '@theme/tokens';

// Existing platform tokens, with a simulator-specific surface vocabulary.
export const SIMULATION_FONT_FAMILY = typography.fontFamily.primary;
export const SIMULATION_TRACES = { current: '#4778FF', reference: '#EAB968' };
export const SIMULATION_THEME = {
  pageBg: colors.ink[950],
  sidebarBg: colors.bg.chrome,
  panelBorder: colors.glass.border,
  panelActive: colors.glass.active,
  textSecondary: colors.fg[3],
  primary: colors.brand.primary,
};
