import React from "react";
import { Box, HStack, Text } from "@chakra-ui/react";
import { colors, borderRadius } from "@theme/tokens";
import { GLASS_SURFACE } from "@theme/glass";

/** Глассовая рамка «чат-окна» для витрины /platform: шапка (точки + статус) + тело. */
export default function ChatWindow({ title = "GPTHub · Чат", children, ...rest }) {
  return (
    <Box {...GLASS_SURFACE} borderRadius={borderRadius.lg} overflow="hidden" {...rest}>
      {/* Шапка окна */}
      <HStack
        justify="space-between"
        px={4}
        py={3}
        borderBottom={`1px solid ${colors.glass.border}`}
        bg={colors.bg.header}
      >
        {/* Светофор-точки + green «на связи»-glow — иллюстративный window-chrome (P3 one-off). */}
        <HStack spacing={1.5}>
          {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
            <Box key={c} boxSize="9px" borderRadius="full" bg={c} opacity={0.55} />
          ))}
          <Text ml={2} fontSize="12px" fontWeight="600" color={colors.fg[3]} noOfLines={1}>
            {title}
          </Text>
        </HStack>
        <HStack spacing={1.5}>
          <Box boxSize="7px" borderRadius="full" bg={colors.success} boxShadow="0 0 8px rgba(16,185,129,0.6)" />
          <Text fontSize="11px" color={colors.fg[4]} display={{ base: "none", sm: "block" }}>На связи</Text>
        </HStack>
      </HStack>

      {/* Тело */}
      <Box px={{ base: 4, md: 5 }} py={{ base: 4, md: 5 }}>
        {children}
      </Box>
    </Box>
  );
}
