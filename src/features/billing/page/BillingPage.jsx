import { useCallback, useEffect, useState } from 'react';
import {
  Box,
  Button,
  HStack,
  Heading,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Link,
  SimpleGrid,
  Text,
  VStack,
} from '@chakra-ui/react';
import { Link as RouterLink } from 'react-router-dom';
import { useAppToast } from '@shared/hooks/useAppToast';
import {
  FiActivity,
  FiArrowUpRight,
  FiAward,
  FiChevronLeft,
  FiRepeat,
  FiZap,
} from '@shared/icons';
import { Reveal } from '@shared/motion/Reveal';
import { Skeleton } from '@shared/feedback/Skeleton';
import Eyebrow from '@shared/brand/Eyebrow';
import { useLayoutControls } from '@app/providers';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, GLASS_SURFACE_STRONG } from '@theme/glass';
import { formatCredits, rubFromCredits, planLabel } from '../lib/credits';
import { useBillingContext } from '../context/BillingContext';
import CreditBar from '../components/CreditBar';
import StatCard from '../components/StatCard';
import PlanCards from '../components/PlanCards';
import TopUpPacks from '../components/TopUpPacks';
import BillingHistory from '../components/BillingHistory';
import TopRequests from '../components/TopRequests';
import SegmentedControl from '@shared/controls/SegmentedControl';
import StateCard from '@shared/feedback/StateCard';
import { MICRO_LABEL_SX } from '@theme/styles';
import SpendAreaChart from '../components/charts/SpendAreaChart';
import BreakdownBars from '../components/charts/BreakdownBars';
import TokenSplitChart from '../components/charts/TokenSplitChart';
import YooKassaWidget from '../components/YooKassaWidget';
import Pager from '@shared/controls/Pager';

const TABS = [
  { key: 'overview', label: 'Обзор' },
  { key: 'analytics', label: 'Аналитика' },
  { key: 'plans', label: 'Тарифы' },
  { key: 'history', label: 'История' },
];

const RANGE_OPTIONS = [
  { key: '7d', label: '7д' },
  { key: '30d', label: '30д' },
  { key: '90d', label: '90д' },
];
const RANGE_LABEL = { '7d': '7 дней', '30d': '30 дней', '90d': '90 дней' };

// Категории фильтра истории; раскрытие в event_type делает бэкенд
// (BillingService.HISTORY_FILTERS) — фильтруем и пагинируем на сервере,
// иначе фильтр видел бы только текущую страницу.
const HISTORY_FILTERS = [
  { key: 'all', label: 'Все' },
  { key: 'usage', label: 'Списания' },
  { key: 'topup', label: 'Пополнения' },
  { key: 'subscription', label: 'Подписка' },
  { key: 'refund', label: 'Возвраты' },
];

const HISTORY_PAGE_SIZE = 20;
const RECENT_LIMIT = 5;

function shortDay(iso) {
  if (!iso) return '—';
  const parts = String(iso).split('-');
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : String(iso);
}

function formatResetDate(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
  } catch {
    return null;
  }
}

function MiniStat({ label, value, sub }) {
  return (
    <VStack align="start" spacing={0.5} minW={0}>
      <Text {...MICRO_LABEL_SX} noOfLines={1}>
        {label}
      </Text>
      <Text fontSize="16px" fontWeight="700" color={CHAT_THEME.textPrimary} lineHeight="1.1" noOfLines={1}>
        {value}
      </Text>
      {sub && (
        <Text fontSize="11px" color={colors.accent.subtleText} noOfLines={1}>
          {sub}
        </Text>
      )}
    </VStack>
  );
}

export default function BillingPage() {
  // Баланс берём из глобального BillingProvider (он уже смонтирован и держит
  // единственный источник) — свой useBalance() слал второй GET /billing/balance.
  const { balance, loading } = useBillingContext();
  const [packs, setPacks] = useState(null);
  const [packsError, setPacksError] = useState(false);
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);
  const [analyticsError, setAnalyticsError] = useState(false);
  const [recent, setRecent] = useState(null); // превью «Последние операции» в Обзоре
  const [recentError, setRecentError] = useState(false);
  const [history, setHistory] = useState(null); // страница вкладки «История»
  const [historyError, setHistoryError] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyFilter, setHistoryFilter] = useState('all');
  const [historyNonce, setHistoryNonce] = useState(0);
  const [range, setRange] = useState('30d');
  const [busy, setBusy] = useState(null);
  const [widgetToken, setWidgetToken] = useState(null);
  const [tab, setTab] = useState('overview');
  const [staticNonce, setStaticNonce] = useState(0);
  const [analyticsNonce, setAnalyticsNonce] = useState(0);
  const toast = useAppToast();

  // Как /chat: занимаем полную ширину layout (иначе ProtectedLayout зажимает
  // контент в узкую колонку maxW="6xl" по центру — на широком экране много
  // пустых полей по бокам). Футер оставляем (это контент-страница).
  const { setVariant } = useLayoutControls();
  useEffect(() => {
    setVariant('full');
    return () => setVariant('container');
  }, [setVariant]);

  // Пакеты и превью истории — один раз при монтировании (и по «Повторить» через nonce).
  useEffect(() => {
    let cancelled = false;
    setPacksError(false);
    setRecentError(false);
    (async () => {
      const { getPacks, getBillingHistory } = await import('@api/billing');
      const [packsData, recentData] = await Promise.all([
        getPacks().catch(() => null),
        getBillingHistory({ limit: RECENT_LIMIT }).catch(() => null),
      ]);
      if (cancelled) return;
      setPacks(packsData);
      setPacksError(!packsData);
      setRecent(recentData);
      setRecentError(!recentData);
    })();
    return () => {
      cancelled = true;
    };
  }, [staticNonce]);

  // История — серверная пагинация: страница перезапрашивается при смене
  // страницы/фильтра. Грузим лениво, только когда вкладка открыта.
  useEffect(() => {
    if (tab !== 'history') return undefined;
    let cancelled = false;
    setHistoryLoading(true);
    setHistoryError(false);
    (async () => {
      const { getBillingHistory } = await import('@api/billing');
      const data = await getBillingHistory({
        limit: HISTORY_PAGE_SIZE,
        offset: historyPage * HISTORY_PAGE_SIZE,
        kind: historyFilter,
      }).catch(() => null);
      if (cancelled) return;
      setHistory(data);
      setHistoryError(!data);
      setHistoryLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, historyPage, historyFilter, historyNonce]);

  const changeHistoryFilter = useCallback((key) => {
    setHistoryFilter(key);
    setHistoryPage(0); // фильтр меняет выборку — старый offset больше не валиден
  }, []);

  // Аналитика — перезапрашивается при смене диапазона (и по «Повторить»).
  useEffect(() => {
    let cancelled = false;
    setAnalyticsLoading(true);
    setAnalyticsError(false);
    (async () => {
      const { getUsageAnalytics } = await import('@api/billing');
      const data = await getUsageAnalytics(range).catch(() => null);
      if (cancelled) return;
      setAnalytics(data);
      setAnalyticsError(!data);
      setAnalyticsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [range, analyticsNonce]);

  const handleCheckout = useCallback(
    async (kind, id) => {
      setBusy(id);
      try {
        const { createCheckout } = await import('@api/billing');
        const body = kind === 'subscription' ? { kind, plan: id } : { kind, pack_id: id };
        const res = await createCheckout(body);
        if (res?.confirmation_token) {
          setWidgetToken(res.confirmation_token);
          return;
        }
        if (res?.checkout_url) {
          window.location.href = res.checkout_url;
          return;
        }
        toast({ title: 'Не удалось создать оплату', status: 'error', duration: 3000 });
      } catch {
        toast({ title: 'Ошибка оплаты', status: 'error', duration: 3000 });
      } finally {
        setBusy(null);
      }
    },
    [toast],
  );

  const limit = balance?.subscription_limit ?? 0;
  const used = Math.max(0, (limit || 0) - (balance?.subscription_remaining || 0));
  const resetDate = formatResetDate(balance?.reset_date);
  const totals = analytics?.totals;
  const rate = totals?.credit_unit_rub;
  const series = analytics?.series || [];
  const byModel = analytics?.by_model || [];
  const byAgent = analytics?.by_agent || [];
  const topRequests = analytics?.top_requests || [];
  const rubBalance = rubFromCredits(balance?.total || 0, rate);
  const rubSpent = rubFromCredits(totals?.credits || 0, rate);
  const rangeHint = `За период: ${RANGE_LABEL[range]}`;

  const recentEvents = recent?.events || [];
  const historyEvents = history?.events || [];
  const historyTotal = history?.total || 0;
  const pageCount = Math.max(1, Math.ceil(historyTotal / HISTORY_PAGE_SIZE));
  const rangeFrom = historyTotal ? historyPage * HISTORY_PAGE_SIZE + 1 : 0;
  const rangeTo = Math.min(historyTotal, historyPage * HISTORY_PAGE_SIZE + historyEvents.length);

  const totalsCells = [
    { label: 'Запросы', value: formatCredits(totals?.requests || 0) },
    { label: 'Кредиты', value: formatCredits(totals?.credits || 0) },
    ...(rubSpent ? [{ label: 'Стоимость', value: rubSpent }] : []),
    { label: 'Ср./запрос', value: formatCredits(totals?.avg_credits_per_request || 0) },
    { label: 'Пик-день', value: shortDay(totals?.peak_day) },
  ];

  return (
    <Box flex="1 0 auto" w="100%" minH="100svh" display="flex" flexDirection="column">
      <Box
        flex="1"
        w="100%"
        maxW="1520px"
        mx="auto"
        px={{ base: 4, md: 8, lg: 12 }}
        py={{ base: 8, md: 10 }}
      >
        {/* Явный возврат в чат: из «меню кредитов» иначе было не выйти (только
            лендинг / кнопка «назад» браузера). */}
        <Box
          as={RouterLink}
          to="/chat"
          display="inline-flex"
          alignItems="center"
          gap={1}
          mb={5}
          fontSize="13px"
          fontWeight="600"
          color={colors.blue[300]}
          _hover={{ color: CHAT_THEME.textPrimary }}
        >
          <FiChevronLeft /> В чат
        </Box>

        <Reveal as={VStack} variant="soft" align="start" spacing={1.5} mb={6}>
          <Eyebrow>Аккаунт</Eyebrow>
          <Heading as="h1" size="lg" color={CHAT_THEME.textPrimary} letterSpacing="-0.01em">
            Биллинг
          </Heading>
          <Text fontSize="13px" color={CHAT_THEME.textSecondary}>
            Баланс, расходы, тарифы и история операций — в одном месте.
          </Text>
        </Reveal>

        {loading && !balance ? (
          <VStack align="stretch" spacing={5} aria-busy="true">
            <Skeleton h="170px" radius={borderRadius.lg} />
            <SimpleGrid columns={{ base: 1, sm: 2, md: 4 }} spacing={3}>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} h="92px" radius={borderRadius.md} />
              ))}
            </SimpleGrid>
          </VStack>
        ) : (
          <VStack align="stretch" spacing={6}>
            <Box overflowX="auto" role="region" aria-label="Разделы биллинга" tabIndex={0} sx={{ '&::-webkit-scrollbar': { display: 'none' } }}>
              <SegmentedControl size="md" options={TABS} value={tab} onChange={setTab} w="max-content" ariaLabel="Разделы биллинга" />
            </Box>

            {/* Обзор */}
            {tab === 'overview' && (
              <Reveal key="overview" as={VStack} variant="soft" className="stagger-children" align="stretch" spacing={5}>
                <Box p={5} {...GLASS_SURFACE} borderRadius={borderRadius.lg}>
                  <HStack justify="space-between" align="flex-start">
                    <Eyebrow>Баланс</Eyebrow>
                    <Button
                      size="xs"
                      variant="ghost"
                      rightIcon={<FiArrowUpRight />}
                      color={colors.accent.subtleText}
                      _hover={{ bg: CHAT_THEME.panelHover }}
                      onClick={() => setTab('plans')}
                    >
                      Пополнить
                    </Button>
                  </HStack>
                  <HStack align="baseline" spacing={2.5} mt={3} mb={4} flexWrap="wrap">
                    <Text fontSize="34px" fontWeight="800" color={CHAT_THEME.textPrimary} lineHeight="1">
                      {formatCredits(balance?.total || 0)}
                    </Text>
                    <Text fontSize="14px" color={CHAT_THEME.textTertiary}>кредитов</Text>
                    {rubBalance && (
                      <Text fontSize="13px" color={colors.iris[300]} fontWeight="600">
                        ≈ {rubBalance}
                      </Text>
                    )}
                  </HStack>

                  {/* Кошельки разведены: подписочный лимит vs докупленные (не сгорают). */}
                  {(limit > 0 || balance?.topup > 0) && (
                    <VStack align="stretch" spacing={3} mt={1}>
                      {limit > 0 && (
                        <Box>
                          <CreditBar used={used} limit={limit} label="Подписка" />
                          {resetDate && (
                            <Text fontSize="11px" color={CHAT_THEME.textTertiary} mt={1.5}>
                              Обновление {resetDate}
                            </Text>
                          )}
                        </Box>
                      )}
                      {balance?.topup > 0 && (
                        <HStack
                          justify="space-between"
                          align="center"
                          px={3}
                          py={2.5}
                          borderRadius={borderRadius.sm}
                          bg={CHAT_THEME.panelHover}
                          border={`1px solid ${colors.border.subtle}`}
                        >
                          <Text fontSize="12px" color={CHAT_THEME.textSecondary}>
                            Докупленные · не сгорают
                          </Text>
                          <Text fontSize="13px" fontWeight="700" color={CHAT_THEME.textPrimary}>
                            {formatCredits(balance.topup)}
                          </Text>
                        </HStack>
                      )}
                    </VStack>
                  )}

                  {series.length > 0 && <SpendAreaChart series={series.slice(-14)} rate={rate} sparkline />}
                </Box>

                <SimpleGrid columns={{ base: 1, sm: 2, md: 4 }} spacing={3}>
                  <StatCard
                    label="Запросов"
                    value={formatCredits(totals?.requests || 0)}
                    icon={FiActivity}
                    accent={colors.blue[300]}
                    hint={rangeHint}
                  />
                  <StatCard
                    label="Потрачено"
                    value={`${formatCredits(totals?.credits || 0)} кр`}
                    subValue={rubSpent}
                    icon={FiZap}
                    accent={colors.iris[300]}
                    hint="Списано кредитов за период"
                  />
                  <StatCard
                    label="Ср. за запрос"
                    value={formatCredits(totals?.avg_credits_per_request || 0)}
                    icon={FiRepeat}
                    accent={colors.cyan[300]}
                    hint="Среднее списание кредитов на один запрос"
                  />
                  <StatCard
                    label="Тариф"
                    value={planLabel(balance?.plan)}
                    icon={FiAward}
                    accent={colors.violet[300]}
                    hint="Текущий тарифный план"
                  />
                </SimpleGrid>

                <Box>
                  <HStack justify="space-between" mb={3}>
                    <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textSecondary}>
                      Последние операции
                    </Text>
                    {recentEvents.length > 0 && (
                      <Button
                        size="xs"
                        variant="ghost"
                        rightIcon={<FiArrowUpRight />}
                        color={colors.accent.subtleText}
                        _hover={{ bg: CHAT_THEME.panelHover }}
                        onClick={() => setTab('history')}
                      >
                        Вся история
                      </Button>
                    )}
                  </HStack>
                  {recentError ? (
                    <StateCard
                      variant="error"
                      message="Не удалось загрузить историю"
                      onRetry={() => setStaticNonce((n) => n + 1)}
                    />
                  ) : recent === null ? (
                    <VStack align="stretch" spacing={2}>
                      {[0, 1, 2].map((i) => (
                        <Skeleton key={i} h="56px" radius={borderRadius.md} />
                      ))}
                    </VStack>
                  ) : (
                    <BillingHistory events={recentEvents} />
                  )}
                </Box>
              </Reveal>
            )}

            {/* Аналитика */}
            {tab === 'analytics' && (
              <Reveal key="analytics" as={VStack} variant="soft" className="stagger-children" align="stretch" spacing={6}>
                <HStack justify="space-between" align="center" flexWrap="wrap" gap={3}>
                  <Eyebrow>Аналитика</Eyebrow>
                  <SegmentedControl
                    as="group"
                    ariaLabel="Период"
                    options={RANGE_OPTIONS}
                    value={range}
                    onChange={setRange}
                    disabled={analyticsLoading}
                  />
                </HStack>

                <SimpleGrid columns={{ base: 1, sm: 2, md: rubSpent ? 5 : 4 }} spacing={3} p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
                  {totalsCells.map((cell) => (
                    <MiniStat key={cell.label} label={cell.label} value={cell.value} sub={cell.sub} />
                  ))}
                </SimpleGrid>

                {analyticsError && !analytics ? (
                  <StateCard
                    variant="error"
                    message="Не удалось загрузить аналитику"
                    onRetry={() => setAnalyticsNonce((n) => n + 1)}
                  />
                ) : analyticsLoading && !analytics ? (
                  <VStack align="stretch" spacing={6} aria-busy="true">
                    <Skeleton h="240px" radius={borderRadius.md} />
                    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={6}>
                      <Skeleton h="200px" radius={borderRadius.md} />
                      <Skeleton h="200px" radius={borderRadius.md} />
                    </SimpleGrid>
                  </VStack>
                ) : (
                  <>
                    <SpendAreaChart series={series} rate={rate} />
                    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={6}>
                      <TokenSplitChart data={byModel} rate={rate} title="По моделям" />
                      <BreakdownBars
                        data={byAgent}
                        title="По типам операций"
                        color={colors.iris[500]}
                        rate={rate}
                      />
                    </SimpleGrid>
                    <TopRequests items={topRequests} rate={rate} />
                  </>
                )}
              </Reveal>
            )}

            {/* Тарифы */}
            {tab === 'plans' && (
              <Reveal key="plans" as={VStack} variant="soft" className="stagger-children" align="stretch" spacing={6}>
                <Box>
                  <Eyebrow>Тарифы</Eyebrow>
                  <Text fontSize="13px" color={CHAT_THEME.textSecondary} mt={2} mb={3}>
                    Месячный пакет кредитов — обновляется каждый период.
                  </Text>
                  {packsError ? (
                    <StateCard
                      variant="error"
                      message="Не удалось загрузить тарифы"
                      onRetry={() => setStaticNonce((n) => n + 1)}
                    />
                  ) : packs === null ? (
                    <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
                      {[0, 1, 2].map((i) => (
                        <Skeleton key={i} h="220px" radius={borderRadius.md} />
                      ))}
                    </SimpleGrid>
                  ) : (
                    <PlanCards
                      plans={packs?.plans || []}
                      currentPlan={balance?.plan}
                      busy={busy}
                      onCheckout={(planId) => handleCheckout('subscription', planId)}
                    />
                  )}
                </Box>
                <Box>
                  <Text fontSize="13px" color={CHAT_THEME.textSecondary} mb={3}>
                    Докупка кредитов (не сгорают)
                  </Text>
                  {packsError ? null : packs === null ? (
                    <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
                      {[0, 1, 2].map((i) => (
                        <Skeleton key={i} h="150px" radius={borderRadius.md} />
                      ))}
                    </SimpleGrid>
                  ) : (
                    <TopUpPacks
                      packs={packs?.packs || []}
                      busy={busy}
                      onCheckout={(packId) => handleCheckout('topup', packId)}
                    />
                  )}
                </Box>

                <Text fontSize="11px" color={CHAT_THEME.textTertiary} lineHeight="1.7">
                  Оплата производится через ЮKassa. Кредиты зачисляются на счёт автоматически
                  сразу после подтверждения оплаты. Нажимая кнопку оплаты, вы соглашаетесь с
                  условиями{' '}
                  <Link as={RouterLink} to="/legal/offer" color={colors.accent.subtleText} textDecoration="underline">
                    Публичной оферты
                  </Link>{' '}
                  и{' '}
                  <Link as={RouterLink} to="/legal/privacy" color={colors.accent.subtleText} textDecoration="underline">
                    Политики конфиденциальности
                  </Link>
                  .
                </Text>
              </Reveal>
            )}

            {/* История */}
            {tab === 'history' && (
              <Reveal key="history" as={VStack} variant="soft" className="stagger-children" align="stretch" spacing={4}>
                <HStack justify="space-between" align="center" flexWrap="wrap" gap={3}>
                  <Eyebrow>История операций</Eyebrow>
                  {historyTotal > 0 && (
                    <Text fontSize="12px" color={CHAT_THEME.textTertiary}>
                      {rangeFrom}–{rangeTo} из {historyTotal}
                    </Text>
                  )}
                </HStack>

                <Box overflowX="auto" role="region" aria-label="Фильтр истории операций" tabIndex={0} sx={{ '&::-webkit-scrollbar': { display: 'none' } }}>
                  <SegmentedControl
                    as="group"
                    ariaLabel="Фильтр операций"
                    options={HISTORY_FILTERS}
                    value={historyFilter}
                    onChange={changeHistoryFilter}
                    disabled={historyLoading}
                    w="max-content"
                  />
                </Box>

                {historyError ? (
                  <StateCard
                    variant="error"
                    message="Не удалось загрузить историю"
                    onRetry={() => setHistoryNonce((n) => n + 1)}
                  />
                ) : history === null ? (
                  <VStack align="stretch" spacing={2}>
                    {[0, 1, 2, 3, 4].map((i) => (
                      <Skeleton key={i} h="56px" radius={borderRadius.md} />
                    ))}
                  </VStack>
                ) : (
                  <>
                    {/* Страница подменяется на месте: не гасим список скелетоном,
                        чтобы не прыгала высота — просто приглушаем на время запроса. */}
                    <Box
                      opacity={historyLoading ? 0.5 : 1}
                      transition="opacity 160ms ease"
                      aria-busy={historyLoading}
                    >
                      <BillingHistory
                        events={historyEvents}
                        emptyMessage={
                          historyFilter === 'all'
                            ? 'Пока нет операций'
                            : 'Нет операций в этой категории'
                        }
                      />
                    </Box>

                    <Box pt={1}>
                      <Pager
                        page={historyPage}
                        pageCount={pageCount}
                        busy={historyLoading}
                        onChange={setHistoryPage}
                      />
                    </Box>
                  </>
                )}
              </Reveal>
            )}
          </VStack>
        )}
      </Box>

      <Modal isOpen={!!widgetToken} onClose={() => setWidgetToken(null)} isCentered size="md">
        <ModalOverlay bg={colors.bg.overlay} />
        <ModalContent {...GLASS_SURFACE_STRONG} borderRadius={borderRadius.lg}>
          <ModalHeader color={CHAT_THEME.textPrimary} fontSize="16px">
            Оплата
          </ModalHeader>
          <ModalCloseButton aria-label="Закрыть окно оплаты" color={CHAT_THEME.textSecondary} />
          <ModalBody pb={6}>
            {widgetToken && (
              <YooKassaWidget
                token={widgetToken}
                returnUrl={`${window.location.origin}/billing/success`}
                onError={() =>
                  toast({ title: 'Ошибка виджета оплаты', status: 'error', duration: 3000 })
                }
              />
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  );
}
