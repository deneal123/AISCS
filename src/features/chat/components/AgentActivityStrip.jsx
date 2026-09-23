import React from 'react';
import { keyframes } from '@emotion/react';
import { Box, Button, HStack, Icon, Text } from '@chakra-ui/react';
import { FiActivity, FiCpu, FiGitBranch, FiSearch, FiTool } from '@shared/icons';
import { colors, borderRadius, motion } from '@theme/tokens';
import { CHAT_THEME } from '../constants/theme';

const iconPulse = keyframes`0%, 100% { opacity: 0.55; transform: scale(0.92); } 50% { opacity: 1; transform: scale(1); }`;
const sweep = keyframes`0% { transform: translateX(-100%); } 100% { transform: translateX(320%); }`;

function pickIcon(title = '') {
  const t = title.toLowerCase();
  if (t.includes('инструмент') || t.includes('tool')) return FiTool;
  if (t.includes('маршрут') || t.includes('routing')) return FiGitBranch;
  if (t.includes('поиск') || t.includes('research') || t.includes('ссыл')) return FiSearch;
  if (t.includes('агент') || t.includes('модел')) return FiCpu;
  return FiActivity;
}

/**
 * Живая строка активности агента: текущий шаг (роутинг → агент → инструмент) из
 * трейс-событий, что и так текут через onAgentEvent. Пульсирующая иконка +
 * бегущий шиммер снизу вместо плоского спиннера. Сворачивается в трейс по
 * завершении (родитель убирает при clearCurrentJob).
 */
export default function AgentActivityStrip({ session, onCancel }) {
  const events = session?.events || [];
  const latest = events.length ? events[events.length - 1] : null;
  const title = latest?.title || 'Обработка запроса…';
  const detail = latest?.detail || '';
  const IconCmp = pickIcon(title);

  return (
    <HStack
      mt={6}
      spacing={3}
      px={4}
      py={3}
      borderRadius={borderRadius.md}
      bg={CHAT_THEME.panelBg}
      border={`1px solid ${CHAT_THEME.panelBorder}`}
      alignSelf="flex-start"
      maxW="100%"
      position="relative"
      overflow="hidden"
      role="status"
      aria-live="polite"
    >
      <Box position="absolute" bottom={0} left={0} right={0} h="2px" overflow="hidden">
        <Box
          position="absolute"
          top={0}
          bottom={0}
          w="30%"
          background={`linear-gradient(90deg, transparent, ${colors.blue[300]}, transparent)`}
          sx={{
            animation: `${sweep} 1.5s ${motion.easeInOut} infinite`,
            '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
          }}
        />
      </Box>

      <Box
        boxSize="30px"
        flexShrink={0}
        borderRadius={borderRadius.sm}
        bg={CHAT_THEME.accentSoft}
        border={`1px solid ${colors.accent.subtleBorder}`}
        display="flex"
        alignItems="center"
        justifyContent="center"
        sx={{
          animation: `${iconPulse} 1.4s ease-in-out infinite`,
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      >
        <Icon as={IconCmp} boxSize="15px" color={colors.blue[300]} />
      </Box>

      <Box minW={0} flex="1">
        <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textPrimary} noOfLines={1}>
          {title}
        </Text>
        {detail ? (
          <Text fontSize="11px" color={CHAT_THEME.textTertiary} noOfLines={1}>
            {detail}
          </Text>
        ) : null}
      </Box>

      {events.length > 1 && (
        <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontFamily="'JetBrains Mono', monospace" flexShrink={0}>
          {events.length} шаг.
        </Text>
      )}
      {onCancel && (
        <Button size="xs" variant="ghost" color={colors.iris[300]} flexShrink={0}
          _hover={{ bg: CHAT_THEME.panelHover }} onClick={onCancel}>
          Стоп
        </Button>
      )}
    </HStack>
  );
}
