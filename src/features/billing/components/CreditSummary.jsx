import { Badge, Box, Button, HStack, Text } from '@chakra-ui/react';
import { useNavigate } from 'react-router-dom';
import { borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';
import { CHAT_THEME } from '../../chat/constants/theme';
import { GHOST_BADGE_BLUE_SX, GHOST_BUTTON_BLUE_SX } from '@theme/styles';
import { formatCredits, planLabel } from '../lib/credits';
import CreditBar from './CreditBar';

export default function CreditSummary({ balance }) {
  const navigate = useNavigate();
  if (!balance) return null;
  const limit = balance.subscription_limit ?? 0;
  const used = Math.max(0, (limit || 0) - (balance.subscription_remaining || 0));

  return (
    <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <HStack justify="space-between" mb={3}>
        <Text
          fontSize="10.5px"
          fontWeight="600"
          color={CHAT_THEME.textTertiary}
          letterSpacing="0.04em"
          textTransform="uppercase"
        >
          Кредиты
        </Text>
        <Badge
          px={2}
          py={0.5}
          borderRadius="full"
          fontSize="10px"
          textTransform="none"
          {...GHOST_BADGE_BLUE_SX}
        >
          {planLabel(balance.plan)}
        </Badge>
      </HStack>
      <Text fontSize="22px" fontWeight="700" color={CHAT_THEME.textPrimary} lineHeight="1.1" mb={3}>
        {formatCredits(balance.total)}
      </Text>
      {limit > 0 && <CreditBar used={used} limit={limit} label="Подписка" />}
      {balance.topup > 0 && (
        <Text fontSize="11px" color={CHAT_THEME.textSecondary} mt={2}>
          + {formatCredits(balance.topup)} докупленных (не сгорают)
        </Text>
      )}
      <Button
        mt={3}
        size="sm"
        w="full"
        h="36px"
        borderRadius={borderRadius.sm}
        fontSize="12.5px"
        fontWeight="600"
        {...GHOST_BUTTON_BLUE_SX}
        onClick={() => navigate('/billing')}
      >
        Управление и пополнение
      </Button>
    </Box>
  );
}
