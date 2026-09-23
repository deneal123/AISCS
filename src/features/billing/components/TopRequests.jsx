import { Box, HStack, Text, VStack } from '@chakra-ui/react';
import { colors, borderRadius, typography } from '@theme/tokens';
import { GLASS_SURFACE, CARD_HOVER_SOFT, CARD_TRANSITION } from '@theme/glass';
import { CHAT_THEME } from '../../chat/constants/theme';
import { formatCredits, formatTokens, rubFromCredits } from '../lib/credits';
import ModelChip from './ModelChip';

/**
 * «Самые дорогие запросы» — стеклянный список top_requests из аналитики.
 * Фича-детект: пусто/отсутствует → компонент скрыт (null). Показывает чип
 * модели, кредиты + ₽ и расщепление prompt/completion токенов.
 */
export default function TopRequests({ items = [], rate }) {
  if (!items.length) return null;
  return (
    <Box>
      <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textSecondary} mb={3}>
        Самые дорогие запросы
      </Text>
      <VStack align="stretch" spacing={2}>
        {items.map((row, index) => {
          const rub = rubFromCredits(row.credits, rate);
          const hasSplit = (row.prompt_tokens || 0) + (row.completion_tokens || 0) > 0;
          return (
            <HStack
              key={`${row.thread_id || 'req'}-${index}`}
              justify="space-between"
              align="center"
              spacing={3}
              p={3}
              {...GLASS_SURFACE}
              borderRadius={borderRadius.md}
              transition={CARD_TRANSITION}
              _hover={CARD_HOVER_SOFT}
            >
              <HStack spacing={3} minW={0}>
                <Box
                  flexShrink={0}
                  boxSize="24px"
                  borderRadius="full"
                  bg={CHAT_THEME.accentSoft}
                  border={`1px solid ${colors.accent.subtleBorder}`}
                  color={colors.blue[300]}
                  fontSize="11px"
                  fontWeight="700"
                  fontFamily={typography.fontFamily.mono}
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                >
                  {index + 1}
                </Box>
                <VStack align="start" spacing={0.5} minW={0}>
                  <ModelChip model={row.model} />
                  <Text fontSize="11px" color={CHAT_THEME.textTertiary} noOfLines={1}>
                    {hasSplit
                      ? `${formatTokens(row.tokens)} токенов · ${formatTokens(row.prompt_tokens)} + ${formatTokens(row.completion_tokens)}`
                      : `${formatTokens(row.tokens)} токенов`}
                  </Text>
                </VStack>
              </HStack>
              <VStack align="end" spacing={0} flexShrink={0}>
                <Text fontSize="13px" fontWeight="700" color={CHAT_THEME.textPrimary}>
                  {formatCredits(row.credits)} кр
                </Text>
                {rub && (
                  <Text fontSize="11px" color={colors.accent.subtleText}>{rub}</Text>
                )}
              </VStack>
            </HStack>
          );
        })}
      </VStack>
    </Box>
  );
}
