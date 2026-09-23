import React from "react";
import { Box, HStack, Icon, IconButton, Text, VStack } from "@chakra-ui/react";
import { FiCheck, FiX } from "@shared/icons";
import { colors, borderRadius, motion } from "@theme/tokens";
import { GLASS_CARD_BASE } from "@theme/glass";
import { CHAT_FONT_FAMILY, CHAT_THEME } from "../constants/theme";

/**
 * Онбординг-карточка на пустом экране чата: прогресс из реальных действий
 * пользователя (лёгкая геймификация). Кольцо прогресса + чеклист. Скрываемая.
 * При завершении всех шагов — деликатное «Готово».
 */
function ProgressRing({ done, total }) {
  const size = 40;
  const stroke = 4;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = total ? done / total : 0;
  return (
    <Box position="relative" boxSize={`${size}px`} flexShrink={0}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colors.border.medium} strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={CHAT_THEME.accent}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          style={{ transition: `stroke-dashoffset 0.5s ${motion.easeOut}` }}
        />
      </svg>
      <Box position="absolute" inset={0} display="flex" alignItems="center" justifyContent="center">
        <Text fontSize="11px" fontWeight="700" color="white">
          {done}/{total}
        </Text>
      </Box>
    </Box>
  );
}

export default function ChatOnboarding({ steps, completedCount, total, allDone, onDismiss }) {
  return (
    <Box
      mt={8}
      mx="auto"
      maxW="440px"
      w="100%"
      p={4}
      {...GLASS_CARD_BASE}
      borderRadius={borderRadius.lg}
      fontFamily={CHAT_FONT_FAMILY}
    >
      <IconButton
        aria-label="Скрыть"
        icon={<FiX />}
        size="xs"
        variant="ghost"
        position="absolute"
        top={2}
        right={2}
        color={CHAT_THEME.textTertiary}
        _hover={{ color: CHAT_THEME.textPrimary, bg: CHAT_THEME.panelHover }}
        onClick={onDismiss}
      />
      <HStack spacing={3} align="center" mb={allDone ? 0 : 4}>
        <ProgressRing done={completedCount} total={total} />
        <VStack align="flex-start" spacing={0}>
          <Text fontSize="14px" fontWeight="700" color="white">
            {allDone ? "Всё готово — вы освоились!" : "Быстрый старт"}
          </Text>
          <Text fontSize="12px" color={CHAT_THEME.textSecondary}>
            {allDone ? "Приятной работы с ассистентом." : "Три шага, чтобы раскрыть возможности."}
          </Text>
        </VStack>
      </HStack>

      {!allDone && (
        <VStack align="stretch" spacing={1.5}>
          {steps.map((step) => (
            <HStack key={step.id} spacing={2.5} px={1}>
              <Box
                boxSize="18px"
                borderRadius="full"
                flexShrink={0}
                display="flex"
                alignItems="center"
                justifyContent="center"
                bg={step.done ? colors.accent.subtle : colors.border.default}
                border={`1px solid ${step.done ? colors.accent.subtleBorder : CHAT_THEME.panelBorder}`}
                transition={`all 200ms ${motion.easeOut}`}
              >
                {step.done && <Icon as={FiCheck} boxSize="11px" color={colors.iris[300]} />}
              </Box>
              <Text
                fontSize="13px"
                color={step.done ? CHAT_THEME.textTertiary : CHAT_THEME.textPrimary}
                textDecoration={step.done ? "line-through" : "none"}
              >
                {step.label}
              </Text>
            </HStack>
          ))}
        </VStack>
      )}
    </Box>
  );
}
