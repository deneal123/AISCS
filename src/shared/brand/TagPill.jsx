import React from "react";
import { Text } from "@chakra-ui/react";
import { colors, typography } from "@theme/tokens";

/**
 * Капабилити-чип: mono-текст в стеклянной таблетке с hover-glow (`.tag-pill`
 * в src/styles/motion.css). Порт рецепта docs/design_transfer/06 (tag pill).
 * Shared brand-примитив: переиспользуется лендингом и авторизацией.
 */
export default function TagPill({ children }) {
  return (
    <Text
      as="span"
      className="tag-pill"
      display="inline-flex"
      alignItems="center"
      px={3}
      py="5px"
      borderRadius="full"
      fontSize="11.5px"
      fontWeight="600"
      letterSpacing="0.04em"
      fontFamily={typography.fontFamily.mono}
      color={colors.fg[3]}
      bg={colors.surface.tint2}
      border={`1px solid ${colors.border.card}`}
    >
      {children}
    </Text>
  );
}
