import { Box, HStack, Text } from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { CHAT_THEME } from '../../chat/constants/theme';
import { creditBarView, formatCredits } from '../lib/credits';

export default function CreditBar({ used = 0, limit = 0, label }) {
  const { percent, color } = creditBarView(used, limit);
  const remaining = Math.max(0, (Number(limit) || 0) - (Number(used) || 0));
  return (
    <Box>
      {label && (
        <HStack justify="space-between" mb={1.5}>
          <Text fontSize="11px" color={CHAT_THEME.textSecondary}>{label}</Text>
          <Text fontSize="11px" color={CHAT_THEME.textTertiary}>{formatCredits(remaining)} осталось</Text>
        </HStack>
      )}
      <Box h="8px" borderRadius="full" bg={colors.border.subtle} overflow="hidden">
        <Box h="full" w={`${percent}%`} bg={color} borderRadius="full" transition="width 0.3s ease" />
      </Box>
    </Box>
  );
}
