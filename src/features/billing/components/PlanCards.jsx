import { Badge, Box, Button, HStack, Icon, SimpleGrid, Text, VStack } from '@chakra-ui/react';
import { FiCheck, FiStar } from '@shared/icons';
import { CHAT_THEME } from '../../chat/constants/theme';
import { GLASS_CARD_BASE, CARD_TOP_LINE, CARD_HOVER_STATE } from '@theme/glass';
import { colors, borderRadius } from '@theme/tokens';
import { GHOST_BADGE_BLUE_SX, GHOST_BUTTON_BLUE_SX } from '@theme/styles';
import { formatCredits, formatRub, planLabel } from '../lib/credits';
import StateCard from '@shared/feedback/StateCard';

// ₽ за 1000 кредитов (подсвечиваем ценность тарифа). Реальный якорь ~0.003 ₽/кредит,
// поэтому ₽/кредит округлялось бы в «0,00»; считаем за 1000, RU-разделитель.
function perCreditLabel(price, credits) {
  const c = Number(credits) || 0;
  const p = Number(price) || 0;
  if (c <= 0 || p <= 0) return null;
  return `${((p / c) * 1000).toFixed(2).replace('.', ',')} ₽ / 1000 кредитов`;
}

function planFeatures(isFree, credits) {
  return isFree
    ? [`${formatCredits(credits)} кредитов каждый месяц`, 'Доступ к чату и агентам']
    : ['Кредиты обновляются ежемесячно', 'Докупка кредитов сверх лимита'];
}

export default function PlanCards({ plans = [], currentPlan, onCheckout, busy }) {
  if (!plans.length) return <StateCard message="Тарифы временно недоступны" />;

  const paid = plans.filter((p) => (p.price_rub || 0) > 0);
  const recommendedId = paid.length
    ? paid.reduce((best, p) => {
        const v = p.credits > 0 ? p.price_rub / p.credits : Infinity;
        const bv = best.credits > 0 ? best.price_rub / best.credits : Infinity;
        return v < bv ? p : best;
      }).id
    : null;

  return (
    <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
      {plans.map((plan) => {
        const isCurrent = plan.id === currentPlan;
        const isFree = (plan.price_rub || 0) <= 0;
        const isRecommended = plan.id === recommendedId;
        const perCredit = perCreditLabel(plan.price_rub, plan.credits);
        return (
          <Box
            key={plan.id}
            p={4}
            // Золотая грань: у рекомендованного тарифа бежит постоянно, у
            // остальных — зажигается на наведении.
            className={isRecommended ? "gold-edge" : "gold-edge-hover"}
            {...GLASS_CARD_BASE}
            borderColor={isRecommended || isCurrent ? colors.border.blue : undefined}
            _after={isRecommended ? { ...CARD_TOP_LINE, opacity: 1 } : CARD_TOP_LINE}
            _hover={CARD_HOVER_STATE}
          >
            <VStack align="stretch" spacing={2}>
              <HStack justify="space-between" align="center">
                <Text fontSize="15px" fontWeight="700" color={CHAT_THEME.textPrimary}>
                  {planLabel(plan.id)}
                </Text>
                {isRecommended && (
                  <Badge
                    {...GHOST_BADGE_BLUE_SX}
                    borderRadius="full"
                    px={2}
                    py={0.5}
                    textTransform="none"
                    fontSize="10px"
                    display="inline-flex"
                    alignItems="center"
                    gap={1}
                  >
                    <Icon as={FiStar} boxSize={2.5} /> Рекомендуем
                  </Badge>
                )}
              </HStack>

              <Text fontSize="20px" fontWeight="700" color={CHAT_THEME.textPrimary}>
                {isFree ? 'Бесплатно' : formatRub(plan.price_rub)}
                {!isFree && (
                  <Text as="span" fontSize="12px" color={CHAT_THEME.textTertiary}>
                    {' '}
                    /мес
                  </Text>
                )}
              </Text>

              <HStack justify="space-between" align="baseline">
                <Text fontSize="12px" color={CHAT_THEME.textSecondary}>
                  {formatCredits(plan.credits)} кредитов/мес
                </Text>
                {perCredit && (
                  <Text fontSize="11px" color={colors.accent.subtleText}>{perCredit}</Text>
                )}
              </HStack>

              <VStack align="stretch" spacing={1} mt={1}>
                {planFeatures(isFree, plan.credits).map((feature) => (
                  <HStack key={feature} spacing={1.5} align="center">
                    <Icon as={FiCheck} boxSize={3} color={colors.cyan[300]} flexShrink={0} />
                    <Text fontSize="11.5px" color={CHAT_THEME.textSecondary}>{feature}</Text>
                  </HStack>
                ))}
              </VStack>

              {isFree ? (
                <Badge
                  alignSelf="start"
                  mt={1}
                  {...GHOST_BADGE_BLUE_SX}
                  borderRadius="full"
                  px={2.5}
                  py={1}
                  textTransform="none"
                  fontSize="11px"
                >
                  {isCurrent ? 'Текущий тариф' : 'Бесплатно'}
                </Badge>
              ) : isCurrent ? (
                <Badge
                  alignSelf="start"
                  mt={1}
                  {...GHOST_BADGE_BLUE_SX}
                  borderRadius="full"
                  px={2.5}
                  py={1}
                  textTransform="none"
                  fontSize="11px"
                >
                  Текущий тариф
                </Badge>
              ) : (
                <Button
                  mt={1}
                  size="sm"
                  borderRadius={borderRadius.sm}
                  isLoading={busy === plan.id}
                  onClick={() => onCheckout?.(plan.id)}
                  {...GHOST_BUTTON_BLUE_SX}
                >
                  Подключить
                </Button>
              )}
            </VStack>
          </Box>
        );
      })}
    </SimpleGrid>
  );
}

