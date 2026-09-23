import React from 'react';
import { Box } from '@chakra-ui/react';
import { colors, borderRadius, shadows, motion } from '@theme/tokens';
import { CARD_TOP_LINE } from '@theme/glass';
import { CHAT_THEME } from '../../constants/theme';

const EASE = motion.easeOut;

/**
 * Стеклянный «кокпит» композера: сам шелл — рамка (стекло + blur + iris-бордер),
 * а вложенная textarea прозрачна и безрамочна. На фокусе (focus-within) кромка
 * светлеет, добавляется мягкое iris-свечение и «зажигается» иридесцентная
 * волосяная линия (инсет от углов, чтобы не нужен был overflow:hidden, который
 * обрезал бы focus-кольца вложенных кнопок). Killswitch blur ≤640px сохранён.
 *
 * Золотая бегущая грань: `busy` (ассистент отвечает) — бежит постоянно, это
 * живой индикатор работы; иначе зажигается по фокусу, когда пишешь. Занимает
 * ::before, поэтому не конфликтует с иридесцентной линией в ::after.
 *
 * Своего backdrop-filter здесь НЕТ намеренно: липкая подложка композера
 * (ChatComposerPanel) уже блюрит фон под собой, и второй слой блюрил
 * заблюренное — двойная растеризация на каждом кадре ввода, без визуальной
 * разницы.
 */
function ComposerShell({ children, busy = false }) {
  return (
    <Box
      className={busy ? 'gold-edge' : 'gold-edge-focus'}
      position="relative"
      w="100%"
      maxW="100%"
      borderRadius={borderRadius.lg}
      bg={CHAT_THEME.inputBg}
      border={`1px solid ${CHAT_THEME.inputBorder}`}
      boxShadow={shadows.glassCard}
      transition={`border-color 200ms ${EASE}, box-shadow 200ms ${EASE}, background 200ms ${EASE}`}
      _after={{ ...CARD_TOP_LINE, left: '18px', right: '18px' }}
      _focusWithin={{
        borderColor: colors.glass.borderHi,
        bg: colors.bg.inputStrong,
        boxShadow: `${shadows.glassCard}, ${shadows.glowSubtle}`,
        _after: { opacity: 1 },
      }}
    >
      {children}
    </Box>
  );
}

export default ComposerShell;
