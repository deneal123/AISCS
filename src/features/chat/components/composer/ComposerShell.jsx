import React from 'react';
import { Box } from '@chakra-ui/react';
import { colors, borderRadius, shadows, motion } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';

const EASE = motion.easeOut;

/**
 * Свечение приглашает к доступному вводу, но не сопровождает набор текста.
 * Общий контракт data-action-hint немедленно гасит грань при focus-within,
 * активации и открытии модалки. Готовность задаёт существующий владелец задачи.
 * Фокус остаётся заметным по статичной рамке, без свечения и изменения размеров.
 *
 * Своего backdrop-filter здесь НЕТ намеренно: липкая подложка композера
 * (ChatComposerPanel) уже блюрит фон под собой, и второй слой блюрил
 * заблюренное — двойная растеризация на каждом кадре ввода, без визуальной
 * разницы.
 */
function ComposerShell({ children, ready = true }) {
  return (
    <Box
      data-composer-input-surface
      data-action-hint={ready ? 'idle' : undefined}
      position="relative"
      w="100%"
      maxW="100%"
      borderRadius={borderRadius.lg}
      bg={CHAT_THEME.inputBg}
      border={`1px solid ${CHAT_THEME.inputBorder}`}
      boxShadow={shadows.glassCard}
      transition={`border-color 200ms ${EASE}, box-shadow 200ms ${EASE}, background 200ms ${EASE}`}
      _focusWithin={{
        borderColor: colors.border.focus,
        bg: colors.bg.inputStrong,
        boxShadow: shadows.glassCard,
      }}
    >
      {children}
    </Box>
  );
}

export default ComposerShell;
