import { Badge, Box, Button, HStack, SimpleGrid, Text, VStack } from '@chakra-ui/react';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_CARD_BASE, CARD_TOP_LINE, CARD_HOVER_STATE } from '@theme/glass';
import { GHOST_BUTTON_BLUE_SX } from '@theme/styles';
import { CHAT_THEME } from '../../chat/constants/theme';
import { formatCredits, formatRub } from '../lib/credits';
import StateCard from '@shared/feedback/StateCard';

function perCreditValue(price, credits) {
  const c = Number(credits) || 0;
  const p = Number(price) || 0;
  return c > 0 && p > 0 ? p / c : null;
}

const SAVINGS_BADGE_SX = {
  bg: colors.successSoft,
  color: colors.success,
  border: `1px solid ${colors.successBorder}`,
};

export default function TopUpPacks({ packs = [], onCheckout, busy }) {
  if (!packs.length) return <StateCard message="Пакеты кредитов временно недоступны" />;

  // База выгоды — самый маленький пакет (худшая удельная цена).
  const byCredits = [...packs].sort((a, b) => (a.credits || 0) - (b.credits || 0));
  const base = byCredits.length ? perCreditValue(byCredits[0].price_rub, byCredits[0].credits) : null;
  const savingsOf = (pack) => {
    const per = perCreditValue(pack.price_rub, pack.credits);
    if (!base || !per || per >= base) return 0;
    return Math.round((1 - per / base) * 100);
  };
  const bestSavings = packs.reduce((max, p) => Math.max(max, savingsOf(p)), 0);

  return (
    <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
      {packs.map((pack) => {
        const per = perCreditValue(pack.price_rub, pack.credits);
        const savings = savingsOf(pack);
        const isBest = savings > 0 && savings === bestSavings;
        return (
          <Box
            key={pack.id}
            p={4}
            // Золотая грань: у самого выгодного пакета бежит постоянно, у
            // остальных — на наведении.
            className={isBest ? "gold-edge" : "gold-edge-hover"}
            {...GLASS_CARD_BASE}
            borderRadius={borderRadius.md}
            borderColor={isBest ? colors.border.blue : undefined}
            _after={isBest ? { ...CARD_TOP_LINE, opacity: 1 } : CARD_TOP_LINE}
            _hover={CARD_HOVER_STATE}
          >
            <VStack align="stretch" spacing={2}>
              <HStack justify="space-between" align="center">
                <Text fontSize="18px" fontWeight="700" color={CHAT_THEME.textPrimary}>
                  {formatCredits(pack.credits)}
                </Text>
                {savings > 0 && (
                  <Badge {...SAVINGS_BADGE_SX} borderRadius="full" px={2} py={0.5} textTransform="none" fontSize="10px">
                    выгода −{savings}%
                  </Badge>
                )}
              </HStack>
              <Text fontSize="12px" color={CHAT_THEME.textSecondary}>кредитов · не сгорают</Text>
              {per && (
                <Text fontSize="11px" color={colors.accent.subtleText}>
                  {(per * 1000).toFixed(2).replace('.', ',')} ₽ / 1000 кредитов
                </Text>
              )}
              <Button
                mt={1}
                size="sm"
                borderRadius={borderRadius.sm}
                isLoading={busy === pack.id}
                onClick={() => onCheckout?.(pack.id)}
                {...GHOST_BUTTON_BLUE_SX}
              >
                Купить за {formatRub(pack.price_rub)}
              </Button>
            </VStack>
          </Box>
        );
      })}
    </SimpleGrid>
  );
}

