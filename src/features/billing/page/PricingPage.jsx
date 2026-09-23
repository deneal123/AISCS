import { useCallback, useEffect, useState } from 'react';
import { Box, Heading, Link, SimpleGrid, Text, VStack } from '@chakra-ui/react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { Reveal } from '@shared/motion/Reveal';
import { Skeleton } from '@shared/feedback/Skeleton';
import StateCard from '@shared/feedback/StateCard';
import Eyebrow from '@shared/brand/Eyebrow';
import { colors, borderRadius } from '@theme/tokens';
import { APP_ROUTES } from '@app/router';
import PlanCards from '../components/PlanCards';
import TopUpPacks from '../components/TopUpPacks';

/**
 * Публичная страница тарифов — доступна БЕЗ входа (в отличие от /billing, который
 * за авторизацией). Нужна для подключения приёма платежей: ЮKassa требует, чтобы
 * товары/услуги и цены были видны без регистрации. Данные берём из публичного
 * /api/billing/packs. Оплата возможна только из аккаунта, поэтому кнопки тарифов
 * для гостя ведут на регистрацию.
 */
export default function PricingPage() {
  const navigate = useNavigate();
  const [packs, setPacks] = useState(null);
  const [error, setError] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    (async () => {
      const { getPacks } = await import('@api/billing');
      const data = await getPacks().catch(() => null);
      if (cancelled) return;
      setPacks(data);
      setError(!data);
    })();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  // Оплатить можно только из аккаунта — гостя ведём регистрироваться.
  const goSignup = useCallback(() => navigate(APP_ROUTES.SIGNUP), [navigate]);

  const plans = packs?.plans || [];
  const topUpPacks = packs?.packs || [];

  return (
    <VStack align="stretch" spacing={{ base: 10, md: 14 }}>
      <Reveal variant="soft" as={Box}>
        <Eyebrow>Тарифы и цены</Eyebrow>
        <Heading
          as="h1"
          size="lg"
          mt={2}
          color={colors.text.primary}
          letterSpacing="-0.01em"
        >
          Оплата по мере использования
        </Heading>
        <Text mt={3} fontSize={{ base: '14px', md: '15px' }} color={colors.text.secondary} maxW="640px">
          Кредитная модель: вы платите за использование, а не за подписку впустую.
          Первые кредиты — бесплатно, карта для старта не нужна. Оплата и списание —
          только из личного кабинета после регистрации.
        </Text>
      </Reveal>

      {/* Тарифы (подписка) */}
      <Reveal variant="soft" as={Box}>
        <Text fontSize="13px" fontWeight="600" color={colors.fg[3]} mb={3}>
          Тарифные планы — месячный пакет кредитов, обновляется каждый период
        </Text>
        {error ? (
          <StateCard variant="error" message="Не удалось загрузить тарифы" onRetry={() => setNonce((n) => n + 1)} />
        ) : packs === null ? (
          <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} h="220px" radius={borderRadius.md} />
            ))}
          </SimpleGrid>
        ) : (
          <PlanCards plans={plans} onCheckout={goSignup} busy={null} />
        )}
      </Reveal>

      {/* Докупка кредитов */}
      <Reveal variant="soft" as={Box}>
        <Text fontSize="13px" fontWeight="600" color={colors.fg[3]} mb={3}>
          Докупка кредитов — не сгорают, тратятся после месячного пакета
        </Text>
        {error ? (
          <StateCard variant="error" message="Не удалось загрузить пакеты кредитов" onRetry={() => setNonce((n) => n + 1)} />
        ) : packs === null ? (
          <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} h="150px" radius={borderRadius.md} />
            ))}
          </SimpleGrid>
        ) : (
          <TopUpPacks packs={topUpPacks} onCheckout={goSignup} busy={null} />
        )}
      </Reveal>

      <Text fontSize="12px" color={colors.fg[4]} lineHeight="1.7">
        Оплата производится через ЮKassa. Кредиты зачисляются автоматически сразу после
        подтверждения оплаты. Оформляя оплату, вы соглашаетесь с условиями{' '}
        <Link as={RouterLink} to="/legal/offer" color={colors.accent.subtleText} textDecoration="underline">
          Публичной оферты
        </Link>{' '}
        и{' '}
        <Link as={RouterLink} to="/legal/privacy" color={colors.accent.subtleText} textDecoration="underline">
          Политики конфиденциальности
        </Link>
        . Реквизиты и контакты — на странице{' '}
        <Link as={RouterLink} to={APP_ROUTES.CONTACTS} color={colors.accent.subtleText} textDecoration="underline">
          Контакты
        </Link>
        .
      </Text>
    </VStack>
  );
}
