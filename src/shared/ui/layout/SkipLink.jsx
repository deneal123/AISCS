import { Box } from "@chakra-ui/react";
import { colors, borderRadius } from "@theme/tokens";

/**
 * «Перейти к содержимому» — первый элемент в таб-порядке (WCAG 2.4.1).
 * Клавиатурному пользователю иначе приходится каждый раз проходить всю шапку.
 * Виден только при фокусе; мышью не встречается никогда.
 *
 * Требует, чтобы у <main> был id="main" (см. PublicLayout/ProtectedLayout).
 */
export default function SkipLink({ href = "#main" }) {
  return (
    <Box
      as="a"
      href={href}
      position="absolute"
      left="16px"
      zIndex={1000}
      top="-100px"
      px={4}
      py={2.5}
      borderRadius={borderRadius.sm}
      bg={colors.bg.menu}
      color={colors.fg[1]}
      border={`1px solid ${colors.border.focus}`}
      fontSize="13px"
      fontWeight="600"
      transition="top 140ms ease-out"
      _focusVisible={{ top: "12px" }}
    >
      Перейти к содержимому
    </Box>
  );
}
