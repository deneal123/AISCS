import { colors, gradients, shadows } from "@theme/tokens";

export const AUTH_PRIMARY_BUTTON_SX = {
  h: "50px",
  borderRadius: "12px",
  bgGradient: gradients.prism,
  color: "white",
  fontWeight: "500",
  boxShadow: shadows.buttonPrimary,
  _hover: { bgGradient: `linear-gradient(135deg, ${colors.accent.hover} 0%, ${colors.iris[500]} 100%)` },
  _active: { bgGradient: `linear-gradient(135deg, ${colors.accent.press} 0%, ${colors.iris[700]} 100%)` },
  _disabled: { bg: colors.accent.glow, color: colors.text.quaternary },
};
