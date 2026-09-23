import React from "react";
import { Box, HStack, Text } from "@chakra-ui/react";
import { colors, typography } from "@theme/tokens";

/**
 * Eyebrow — mono-лейбл с анимированной линией-акцентом (draws 0→20px на `.in`
 * родительского Reveal). Класс `.eyebrow-line` в src/styles/motion.css.
 * Порт рецепта docs/design_transfer/06 (Eyebrow) в JS.
 * Shared brand-примитив: переиспользуется лендингом и авторизацией.
 */
export default function Eyebrow({ children, className, ...rest }) {
  return (
    <HStack spacing={2.5} align="center" className={className} {...rest}>
      <Box
        className="eyebrow-line"
        h="2px"
        flexShrink={0}
        borderRadius="2px"
        bg={`linear-gradient(90deg, ${colors.blue[300]}, ${colors.cyan[300]})`}
      />
      {/* Метрики эталона: 11px / 600 / tracking 0 (у нас было 12px / 700 / 0.16em —
          eyebrow читался заметно разреженнее, чем у них). */}
      <Text
        fontSize="11px"
        fontWeight="600"
        letterSpacing="0"
        textTransform="uppercase"
        color={colors.blue[300]}
        fontFamily={typography.fontFamily.mono}
      >
        {children}
      </Text>
    </HStack>
  );
}
