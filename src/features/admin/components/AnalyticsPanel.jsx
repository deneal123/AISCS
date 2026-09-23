import { useEffect, useMemo, useState } from 'react';
import { Badge, Box, Button, Checkbox, HStack, Icon, IconButton, Input, SimpleGrid, Text, VStack } from '@chakra-ui/react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  FiActivity,
  FiAlertTriangle,
  FiArrowDownRight,
  FiArrowUpRight,
  FiClock,
  FiCreditCard,
  FiDatabase,
  FiKey,
  FiPercent,
  FiRepeat,
  FiRotateCcw,
  FiStar,
  FiTrendingDown,
  FiTrendingUp,
  FiUsers,
  FiZap,
} from '@shared/icons';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, GLASS_SURFACE_STRONG, CARD_HOVER_SOFT, CARD_TRANSITION } from '@theme/glass';
import { GHOST_BADGE_BLUE_SX, MICRO_LABEL_SX } from '@theme/styles';
import { Skeleton } from '@shared/feedback/Skeleton';
import StateCard from '@shared/feedback/StateCard';
import SegmentedControl from '@shared/controls/SegmentedControl';

const RANGES = [
  { key: '7d', label: '7д' },
  { key: '30d', label: '30д' },
  { key: '90d', label: '90д' },
];
const RANGE_LABEL = { '7d': '7 дней', '30d': '30 дней', '90d': '90 дней' };

// Гранулярность P&L-графика: сервер отдаёт готовые свёртки daily/weekly/monthly.
const GRAINS = [
  { key: 'daily', label: 'Дни' },
  { key: 'weekly', label: 'Недели' },
  { key: 'monthly', label: 'Месяцы' },
];

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

const fmt = (n) => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
const rub = (n) => `${Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽`;
const pct = (n) => `${Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`;
const shortDay = (iso) => {
  const p = String(iso || '').split('-');
  return p.length === 3 ? `${p[2]}.${p[1]}` : String(iso || '');
};
// Короткое имя модели для оси: последний сегмент после «/» или «:».
const shortModel = (id) => String(id || '').split(/[/:]/).pop() || id;
// Дельта к прошлому периоду того же размера (сервер отдаёт `finance.previous`).
const delta = (now, prev) => {
  const a = Number(now || 0);
  const b = Number(prev || 0);
  if (!b) return a > 0 ? 100 : 0;
  return ((a - b) / Math.abs(b)) * 100;
};

function ChartTip({ active, payload, label, unit = '', money = false }) {
  if (!active || !payload?.length) return null;
  return (
    <Box {...GLASS_SURFACE_STRONG} borderRadius={borderRadius.sm} px={3} py={2}>
      {label && (
        <Text fontSize="11px" color={CHAT_THEME.textTertiary} mb={0.5}>{shortDay(label)}</Text>
      )}
      {payload.map((p) => (
        <HStack key={p.dataKey || p.name} spacing={2} justify="space-between">
          {p.name && (
            <Text fontSize="11px" color={CHAT_THEME.textTertiary}>{p.name}</Text>
          )}
          <Text fontSize="12px" color={p.color || CHAT_THEME.textPrimary} fontWeight="600">
            {money ? rub(p.value) : `${fmt(p.value)}${unit}`}
          </Text>
        </HStack>
      ))}
    </Box>
  );
}

function ChartCard({ label, hint, children }) {
  return (
    <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <HStack justify="space-between" align="center" mb={3} gap={2} minH="22px">
        <Text {...MICRO_LABEL_SX}>{label}</Text>
        {/* hint — строка-подпись ИЛИ готовый контрол (переключатель гранулярности);
            контрол нельзя заворачивать в Text: это <p>, а внутри был бы <div>. */}
        {typeof hint === 'string' ? (
          <Text fontSize="11px" color={CHAT_THEME.textTertiary} noOfLines={1}>{hint}</Text>
        ) : (
          hint || null
        )}
      </HStack>
      {children}
    </Box>
  );
}

/**
 * Плитка метрики. `trend` — % к прошлому периоду; `invert` — метрика, у которой
 * рост это плохо (себестоимость): полярность цвета переворачивается. Изменение
 * ниже 0.05% считаем нулевым и стрелку не рисуем — «↗ 0%» вводило бы в заблуждение.
 */
function StatTile({ label, value, icon, accent, sub, trend, invert = false }) {
  const t = Number(trend);
  const hasTrend = Number.isFinite(t) && Math.abs(t) >= 0.05;
  const up = t > 0;
  const good = invert ? !up : up;
  const trendColor = good ? colors.success : colors.error;
  return (
    <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md} transition={CARD_TRANSITION} _hover={CARD_HOVER_SOFT}>
      <HStack spacing={2} mb={1.5} minW={0}>
        <Icon as={icon} boxSize={3.5} color={accent} flexShrink={0} />
        <Text {...MICRO_LABEL_SX} noOfLines={1}>{label}</Text>
      </HStack>
      <Text fontSize="22px" fontWeight="700" color={CHAT_THEME.textPrimary} lineHeight="1.1" noOfLines={1}>
        {value}
      </Text>
      <HStack spacing={1.5} mt={1} minW={0}>
        {hasTrend && (
          <HStack spacing={0.5} flexShrink={0}>
            <Icon as={up ? FiArrowUpRight : FiArrowDownRight} boxSize={3} color={trendColor} />
            <Text fontSize="11px" fontWeight="600" color={trendColor}>
              {pct(Math.abs(t))}
            </Text>
          </HStack>
        )}
        {sub && (
          <Text fontSize="11px" color={CHAT_THEME.textTertiary} noOfLines={1}>{sub}</Text>
        )}
      </HStack>
    </Box>
  );
}

/** Компактная плитка «окна» (сегодня / неделя / месяц): доход и прибыль. */
function WindowTile({ label, data }) {
  const profit = Number(data?.profit_rub || 0);
  const zero = Math.abs(profit) < 0.005; // ровно ноль — нейтрально, без «+0 ₽» зелёным
  const profitColor = zero
    ? CHAT_THEME.textTertiary
    : profit > 0
      ? colors.success
      : colors.error;
  return (
    <Box p={3.5} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <Text {...MICRO_LABEL_SX} mb={1.5}>{label}</Text>
      <Text fontSize="18px" fontWeight="700" color={CHAT_THEME.textPrimary} lineHeight="1.1">
        {rub(data?.revenue_rub)}
      </Text>
      <HStack spacing={1.5} mt={1} flexWrap="wrap">
        <Text fontSize="11px" color={CHAT_THEME.textTertiary}>
          расход {rub(data?.cost_rub)} ·
        </Text>
        <Text fontSize="11px" fontWeight="600" color={profitColor}>
          прибыль {zero ? rub(0) : `${profit > 0 ? '+' : '−'}${rub(Math.abs(profit))}`}
        </Text>
      </HStack>
    </Box>
  );
}

function HBar({ data, color }) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(140, (data.length || 1) * 34)}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 4, bottom: 0 }} barCategoryGap="26%">
        <XAxis type="number" tick={{ fontSize: 10, fill: colors.fg[4] }} tickFormatter={fmt} />
        <YAxis
          type="category" dataKey="name" width={150} interval={0}
          tickFormatter={shortModel} tick={{ fontSize: 10.5, fill: colors.fg[3] }}
        />
        <Tooltip content={<ChartTip unit=" кр" />} cursor={{ fill: colors.border.medium }} />
        <Bar dataKey="credits" fill={color} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// Статус провайдеров: цветной индикатор — зелёный (работает: ключ есть + отвечает),
// красный (настроен, но недоступен — напр. кончился биллинг), серый (не настроен).
// Остаток провайдера → человекочитаемо. Показываем только там, где провайдер его
// реально отдаёт (у нас — OpenRouter); у остальных balance отсутствует и строки нет.
function formatBalance(b) {
  if (!b) return null;
  const { remaining, limit, currency } = b;
  if (remaining === null || remaining === undefined) {
    return limit === null ? 'без лимита' : null;
  }
  const cur = currency === 'USD' ? '$' : `${currency || ''} `;
  const rem = typeof remaining === 'number' ? remaining.toFixed(2) : remaining;
  return limit != null ? `${cur}${rem} из ${cur}${limit}` : `${cur}${rem}`;
}

function ProviderHealthCard({ health, onRecheck, onToggle, rechecking, togglingName }) {
  const providers = health?.providers || {};
  const active = health?.active_provider;
  const entries = Object.entries(providers);
  if (!entries.length) return null;
  // Статус меряет РЕАЛЬНЫЙ chat-запрос (не /models). Три состояния «недоступен» раздельно:
  // disabled (выключен админом), blocked (health-блок), недостижим по последней пробе.
  const dotColor = (p) => {
    if (p.disabled) return colors.fg[4];         // выключен админом — серый
    if (!p.configured) return colors.fg[4];
    if (p.blocked) return colors.error;          // заблокирован проверкой
    return p.reachable ? colors.success : colors.error;
  };
  const label = (p) => {
    if (p.disabled) return 'выключен';
    if (!p.configured) return 'не настроен';
    if (p.blocked) return p.reason ? `заблокирован: ${p.reason}` : 'заблокирован';
    if (p.reachable) return 'работает';
    return p.reason || 'недоступен';
  };
  return (
    <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <HStack justify="space-between" mb={2.5}>
        <Text {...MICRO_LABEL_SX}>Статус провайдеров</Text>
        <Button size="xs" variant="outline" onClick={onRecheck} isLoading={rechecking} loadingText="Проверяю">
          Проверить
        </Button>
      </HStack>
      {health?.status?.next_action && (
        <HStack mb={2.5} spacing={2} flexWrap="wrap">
          <Badge colorScheme={health.status.level === 'critical' ? 'red' : health.status.level === 'warning' ? 'yellow' : 'green'} textTransform="none">
            {health.status.level || 'normal'}
          </Badge>
          <Text fontSize="11px" color={CHAT_THEME.textSecondary} flex="1 1 12rem" minW={0} overflowWrap="anywhere">
            {health.status.next_action}
          </Text>
          {health.observed_at && <Text fontSize="10px" color={CHAT_THEME.textTertiary}>проверено {String(health.observed_at).slice(0, 16).replace('T', ' ')}</Text>}
        </HStack>
      )}
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={2}>
        {entries.map(([name, p]) => {
          const bal = formatBalance(p.balance);
          const lowBalance = p.balance && typeof p.balance.remaining === 'number' && p.balance.remaining <= 0;
          return (
            <VStack key={name} align="stretch" spacing={1} px={2.5} py={2} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover}>
              <HStack spacing={2}>
                <Checkbox
                  size="sm"
                  isChecked={!p.disabled}
                  isDisabled={togglingName === name}
                  onChange={(e) => onToggle(name, e.target.checked)}
                  aria-label={`${p.disabled ? 'Включить' : 'Выключить'} провайдера ${name}`}
                  title={p.disabled ? 'включить провайдера' : 'выключить провайдера'}
                  minW="44px"
                  minH="44px"
                  display="inline-flex"
                  alignItems="center"
                  justifyContent="center"
                />
                <Box w="8px" h="8px" borderRadius="full" bg={dotColor(p)} flexShrink={0} title={p.error || label(p)} />
                <Text fontSize="12px" fontWeight="600" color={CHAT_THEME.textPrimary} noOfLines={1}>{name}</Text>
                {active === name && (
                  <Badge {...GHOST_BADGE_BLUE_SX} fontSize="9px" px={1.5} py={0} textTransform="none">активен</Badge>
                )}
                <Text
                  fontSize="10.5px"
                  color={p.reachable && !p.blocked && !p.disabled ? CHAT_THEME.textTertiary : colors.error}
                  ml="auto"
                  flex="1 1 5rem"
                  minW={0}
                  textAlign="right"
                  overflowWrap="anywhere"
                  noOfLines={2}
                >
                  {label(p)}
                </Text>
              </HStack>
              {bal && (
                <HStack spacing={1.5} pl="16px">
                  <Text fontSize="10px" color={CHAT_THEME.textTertiary}>баланс:</Text>
                  <Text fontSize="10.5px" fontWeight="600" fontFamily="'JetBrains Mono', monospace" color={lowBalance ? colors.error : colors.success}>{bal}</Text>
                </HStack>
              )}
            </VStack>
          );
        })}
      </SimpleGrid>
    </Box>
  );
}

// Замена API-ключей провайдеров без рестарта стека. Ключи наружу не отдаются —
// показываем только источник (окружение/админка) и дату. Ввод маскируется.
function ProviderKeysCard() {
  const [rows, setRows] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [busy, setBusy] = useState('');
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { getProviderKeys } = await import('@api/admin');
      const res = await getProviderKeys().catch(() => null);
      if (!cancelled) setRows(res?.providers || []);
    })();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const save = async (provider) => {
    const key = (drafts[provider] || '').trim();
    if (!key) return;
    setBusy(provider);
    try {
      const { setProviderKey } = await import('@api/admin');
      await setProviderKey(provider, key);
      setDrafts((d) => ({ ...d, [provider]: '' }));
      setNonce((n) => n + 1);
    } catch {
      /* оставляем черновик, чтобы можно было повторить */
    } finally {
      setBusy('');
    }
  };

  const remove = async (provider) => {
    setBusy(provider);
    try {
      const { deleteProviderKey } = await import('@api/admin');
      await deleteProviderKey(provider);
      setNonce((n) => n + 1);
    } catch {
      /* no-op */
    } finally {
      setBusy('');
    }
  };

  if (!rows?.length) return null;
  const sourceLabel = (s) => (s === 'override' ? 'из админки' : s === 'env' ? 'из окружения' : 'нет ключа');

  return (
    <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <HStack mb={1.5} spacing={2}>
        <Icon as={FiKey} boxSize="13px" color={colors.blue[300]} />
        <Text {...MICRO_LABEL_SX}>Ключи провайдеров</Text>
      </HStack>
      <Text fontSize="11px" color={CHAT_THEME.textTertiary} mb={3} lineHeight="1.5">
        Замена применяется сразу, без перезапуска стека. Ключи хранятся в зашифрованном виде и наружу не отдаются.
      </Text>
      <VStack align="stretch" spacing={2}>
        {rows.map((r) => (
          <HStack
            key={r.provider}
            spacing={2}
            px={2.5}
            py={2}
            borderRadius={borderRadius.sm}
            bg={CHAT_THEME.panelHover}
            flexWrap="wrap"
            align={{ base: 'stretch', sm: 'center' }}
            flexDirection={{ base: 'column', sm: 'row' }}
          >
            <Text fontSize="12px" fontWeight="600" color={CHAT_THEME.textPrimary} minW={{ base: 0, sm: '70px' }}>{r.provider}</Text>
            <Badge
              {...(r.source === 'override' ? GHOST_BADGE_BLUE_SX : {})}
              fontSize="9px"
              px={1.5}
              py={0}
              textTransform="none"
              bg={r.source === 'override' ? undefined : CHAT_THEME.panelBg}
              color={r.source === 'none' ? colors.error : CHAT_THEME.textTertiary}
            >
              {sourceLabel(r.source)}
            </Badge>
            <Input
              type="password"
              size="xs"
              autoComplete="new-password"
              placeholder="новый ключ…"
              value={drafts[r.provider] || ''}
              onChange={(e) => setDrafts((d) => ({ ...d, [r.provider]: e.target.value }))}
              onKeyDown={(e) => { if (e.key === 'Enter') save(r.provider); }}
              flex="1"
              w={{ base: '100%', sm: 'auto' }}
              minW={{ base: 0, sm: '130px' }}
              bg={CHAT_THEME.inputBg}
              borderColor={CHAT_THEME.inputBorder}
              color={CHAT_THEME.textPrimary}
              borderRadius={borderRadius.sm}
              _placeholder={{ color: CHAT_THEME.textTertiary }}
            />
            <Button
              size="xs"
              variant="outline"
              borderColor={colors.accent.subtleBorder}
              color={colors.blue[300]}
              isDisabled={!(drafts[r.provider] || '').trim() || busy === r.provider}
              isLoading={busy === r.provider}
              onClick={() => save(r.provider)}
              minH={{ base: '40px', sm: 'auto' }}
            >
              Заменить
            </Button>
            {r.has_override && (
              <IconButton
                size="xs"
                variant="ghost"
                aria-label="Сбросить к ключу из окружения"
                title="Сбросить к ключу из окружения"
                icon={<FiRotateCcw />}
                color={CHAT_THEME.textTertiary}
                isDisabled={busy === r.provider}
                onClick={() => remove(r.provider)}
                boxSize={{ base: '44px', sm: '32px' }}
              />
            )}
          </HStack>
        ))}
      </VStack>
    </Box>
  );
}

// Эмбеддер MemOS: модель + размерность. Смена ПОЛНОСТЬЮ сбрасывает память MemOS
// (коллекция Qdrant привязана к размерности) и применяется после рестарта memos.
function MemosEmbedderCard() {
  const [model, setModel] = useState('');
  const [dim, setDim] = useState('');
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { getAdminSettings } = await import('@api/admin');
      const res = await getAdminSettings().catch(() => null);
      const items = res?.settings || [];
      const m = items.find((s) => s.key === 'agents.memos_embedder_model');
      const d = items.find((s) => s.key === 'agents.memos_embedder_dim');
      if (!cancelled) {
        setModel(String(m?.value ?? ''));
        setDim(String(d?.value ?? ''));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const apply = async () => {
    if (!model.trim() || !Number(dim)) return;
    setBusy('apply');
    setStatus('');
    try {
      const { setMemosEmbedder } = await import('@api/admin');
      const res = await setMemosEmbedder(model.trim(), Number(dim));
      setStatus(res?.wipe?.ok
        ? 'Применено. Память MemOS сброшена — перезапустите сервис memos, чтобы задействовать новый эмбеддер.'
        : 'Настройка сохранена, но сброс памяти не подтверждён.');
    } catch {
      setStatus('Не удалось применить.');
    } finally {
      setBusy('');
    }
  };

  const wipe = async () => {
    setBusy('wipe');
    setStatus('');
    try {
      const { wipeMemos } = await import('@api/admin');
      const res = await wipeMemos();
      setStatus(res?.ok ? 'Память MemOS полностью сброшена.' : 'Сброс не удался.');
    } catch {
      setStatus('Ошибка сброса.');
    } finally {
      setBusy('');
    }
  };

  return (
    <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <HStack mb={1.5} spacing={2}>
        <Icon as={FiDatabase} boxSize="13px" color={colors.blue[300]} />
        <Text {...MICRO_LABEL_SX}>Эмбеддер MemOS</Text>
      </HStack>
      <Text fontSize="11px" color={CHAT_THEME.textTertiary} mb={3} lineHeight="1.5">
        Смена эмбеддера ПОЛНОСТЬЮ сбрасывает семантическую память MemOS (коллекция привязана к размерности) и применяется после рестарта memos.
      </Text>
      <HStack spacing={2} flexWrap="wrap" align={{ base: 'stretch', sm: 'center' }} flexDirection={{ base: 'column', sm: 'row' }}>
        <Input
          size="xs"
          flex="1"
          minW={{ base: 0, sm: '180px' }}
          w={{ base: '100%', sm: 'auto' }}
          placeholder="провайдер:модель"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          bg={CHAT_THEME.inputBg}
          borderColor={CHAT_THEME.inputBorder}
          color={CHAT_THEME.textPrimary}
          borderRadius={borderRadius.sm}
        />
        <Input
          size="xs"
          w={{ base: '100%', sm: '110px' }}
          type="number"
          placeholder="размерность"
          value={dim}
          onChange={(e) => setDim(e.target.value)}
          bg={CHAT_THEME.inputBg}
          borderColor={CHAT_THEME.inputBorder}
          color={CHAT_THEME.textPrimary}
          borderRadius={borderRadius.sm}
        />
      </HStack>
      <HStack spacing={2} mt={2} flexWrap="wrap">
        <Button
          size="xs"
          variant="outline"
          borderColor={colors.accent.subtleBorder}
          color={colors.blue[300]}
          isDisabled={!model.trim() || !Number(dim) || busy === 'apply'}
          isLoading={busy === 'apply'}
          onClick={apply}
        >
          Применить (сбросит память)
        </Button>
        <Button
          size="xs"
          variant="ghost"
          color={CHAT_THEME.textTertiary}
          isLoading={busy === 'wipe'}
          onClick={wipe}
        >
          Сбросить память
        </Button>
      </HStack>
      {status && (
        <Text fontSize="11px" color={CHAT_THEME.textSecondary} mt={2} lineHeight="1.5">{status}</Text>
      )}
    </Box>
  );
}

export default function AnalyticsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [range, setRange] = useState('30d');
  const [grain, setGrain] = useState('daily');
  const [nonce, setNonce] = useState(0);
  const [health, setHealth] = useState(null);
  const [rechecking, setRechecking] = useState(false);
  const [togglingName, setTogglingName] = useState('');

  // Кнопка «Проверить»: живая проба всех провайдеров + управление health-блоком на бэке.
  const handleRecheck = async () => {
    setRechecking(true);
    try {
      const { recheckProvidersHealth } = await import('@api/admin');
      const res = await recheckProvidersHealth().catch(() => null);
      if (res) setHealth(res);
    } finally {
      setRechecking(false);
    }
  };

  // Чекбокс вкл/выкл провайдера → сохраняем всю мапу agents.provider_enabled (явные true/false
  // по всем, чтобы не терять чужие значения). Выключенный скрыт у юзеров и не пробуется.
  const handleToggleProvider = async (name, enabled) => {
    setTogglingName(name);
    try {
      const providers = health?.providers || {};
      const map = Object.fromEntries(
        Object.entries(providers).map(([n, p]) => [n, n === name ? enabled : !p.disabled]),
      );
      const { putAdminSetting, getProvidersHealth } = await import('@api/admin');
      await putAdminSetting('agents.provider_enabled', map);
      const res = await getProvidersHealth().catch(() => null);
      if (res) setHealth(res);
    } finally {
      setTogglingName('');
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    (async () => {
      const { getAdminAnalytics } = await import('@api/admin');
      const res = await getAdminAnalytics(range).catch(() => null);
      if (cancelled) return;
      setData(res);
      setError(!res);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [range, nonce]);

  // Живой статус провайдеров — отдельным запросом (не тормозит основную аналитику).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { getProvidersHealth } = await import('@api/admin');
      const res = await getProvidersHealth().catch(() => null);
      if (!cancelled) setHealth(res);
    })();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const totals = data?.totals || {};
  const flags = data?.abuse_flags || [];
  const series = data?.series || [];
  const byModel = data?.by_model || [];
  const byAgent = data?.by_agent || [];
  const topRequests = data?.top_requests || [];

  // useMemo: иначе новый объект на каждый рендер ломает мемоизацию графиков ниже.
  const finance = useMemo(() => data?.finance || {}, [data]);
  const fin = finance.totals || {};
  const prev = finance.previous || {};
  const windows = finance.windows || {};
  const sales = finance.sales || [];
  const users = data?.users || {};
  const uTotals = users.totals || {};
  const plans = users.plans || [];
  const topUsers = users.top || [];

  // P&L под выбранную гранулярность: у дней ключ `day`, у свёрток — `period`.
  const pnl = useMemo(() => {
    const rows = finance[grain] || [];
    return rows.map((r) => ({
      label: r.day || r.period,
      revenue: r.revenue_rub,
      cost: r.cost_rub,
      profit: r.profit_rub,
    }));
  }, [finance, grain]);

  // Активность/регистрации по дням — из дневного P&L (там уже слиты обе метрики).
  const activity = useMemo(
    () =>
      (finance.daily || []).map((r) => ({
        label: r.day,
        active: r.active_users,
        signups: r.new_users,
        requests: r.requests,
      })),
    [finance.daily],
  );

  // Без useMemo это новый массив на каждый рендер — recharts перерисовывал оба
  // BarChart с проигрыванием entry-анимации при любом клике по диапазону/гранулярности.
  const hourly = useMemo(
    () =>
      (users.activity_hourly || []).map((h) => ({
        label: `${String(h.hour).padStart(2, '0')}`,
        requests: h.requests,
        users: h.users,
      })),
    [users.activity_hourly],
  );
  const weekday = useMemo(
    () =>
      (users.activity_weekday || []).map((d) => ({
        label: WEEKDAYS[d.dow - 1] || d.dow,
        requests: d.requests,
        users: d.users,
      })),
    [users.activity_weekday],
  );

  const profitPositive = Number(fin.profit_rub || 0) >= 0;

  return (
    <VStack align="stretch" spacing={5}>
      <HStack justify="space-between" align="center" flexWrap="wrap" gap={3}>
        <Text {...MICRO_LABEL_SX} color={CHAT_THEME.textSecondary}>За период: {RANGE_LABEL[range]}</Text>
        <SegmentedControl as="group" ariaLabel="Период" options={RANGES} value={range} onChange={setRange} disabled={loading} />
      </HStack>

      <ProviderHealthCard
        health={health}
        onRecheck={handleRecheck}
        onToggle={handleToggleProvider}
        rechecking={rechecking}
        togglingName={togglingName}
      />

      <ProviderKeysCard />

      <MemosEmbedderCard />

      {error ? (
        <StateCard variant="error" message="Не удалось загрузить аналитику" onRetry={() => setNonce((n) => n + 1)} />
      ) : loading ? (
        <VStack align="stretch" spacing={5} aria-busy="true">
          <SimpleGrid columns={{ base: 1, sm: 2, md: 4 }} spacing={3}>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} h="84px" radius={borderRadius.md} />
            ))}
          </SimpleGrid>
          <Skeleton h="240px" radius={borderRadius.md} />
          <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={4}>
            <Skeleton h="200px" radius={borderRadius.md} />
            <Skeleton h="200px" radius={borderRadius.md} />
          </SimpleGrid>
        </VStack>
      ) : (
        <>
          {/* ── ФИНАНСЫ ─────────────────────────────────────────────────── */}
          <Text {...MICRO_LABEL_SX} color={CHAT_THEME.textSecondary}>Финансы</Text>

          <SimpleGrid columns={{ base: 1, sm: 2, md: 4 }} spacing={3}>
            <StatTile
              label="Доход" value={rub(fin.revenue_rub)} icon={FiTrendingUp} accent={colors.success}
              trend={delta(fin.revenue_rub, prev.revenue_rub)}
              sub={`подписки ${rub(fin.subscription_rub)} · пополнения ${rub(fin.topup_rub)}`}
            />
            <StatTile
              label="Себестоимость" value={rub(fin.cost_rub)} icon={FiTrendingDown} accent={colors.warning}
              trend={delta(fin.cost_rub, prev.cost_rub)} invert
              sub="реальный расход провайдерам"
            />
            <StatTile
              label="Чистая прибыль" value={rub(fin.profit_rub)} icon={FiZap}
              accent={profitPositive ? colors.success : colors.error}
              trend={delta(fin.profit_rub, prev.profit_rub)}
              sub={`возвраты ${rub(fin.refund_rub)}`}
            />
            <StatTile
              label="Маржа" value={pct(fin.margin_pct)} icon={FiPercent} accent={colors.iris[300]}
              sub={`MRR ${rub(fin.mrr_rub)}`}
            />
          </SimpleGrid>

          <SimpleGrid columns={{ base: 1, sm: 3 }} spacing={3}>
            <WindowTile label="Сегодня" data={windows.today} />
            <WindowTile label="Текущая неделя" data={windows.week} />
            <WindowTile label="Текущий месяц" data={windows.month} />
          </SimpleGrid>

          {pnl.length > 0 && (
            <ChartCard
              label="Доход · себестоимость · прибыль"
              hint={<SegmentedControl as="group" ariaLabel="Гранулярность" options={GRAINS} value={grain} onChange={setGrain} />}
            >
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={pnl} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.surface.tint3} />
                  <XAxis dataKey="label" tickFormatter={shortDay} tick={{ fontSize: 10, fill: colors.fg[4] }} />
                  <YAxis tick={{ fontSize: 10, fill: colors.fg[4] }} />
                  <Tooltip content={<ChartTip money />} cursor={{ fill: colors.border.medium }} />
                  <Legend wrapperStyle={{ fontSize: 11, color: colors.fg[3] }} />
                  <Bar name="Доход" dataKey="revenue" fill={colors.success} radius={[4, 4, 0, 0]} />
                  <Bar name="Себестоимость" dataKey="cost" fill={colors.warning} radius={[4, 4, 0, 0]} />
                  <Line name="Прибыль" type="monotone" dataKey="profit" stroke={colors.blue[300]} strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>
          )}

          <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={4}>
            <ChartCard label="Продажи" hint={`${fin.subscription_count || 0} подписок · ${fin.topup_count || 0} пополнений`}>
              {sales.length > 0 ? (
                <VStack align="stretch" spacing={1.5}>
                  {sales.map((s) => (
                    <HStack key={`${s.kind}-${s.item}`} justify="space-between" p={2.5} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover}>
                      <HStack spacing={2} minW={0}>
                        <Icon as={s.kind === 'subscription' ? FiStar : FiCreditCard} boxSize={3.5}
                          color={s.kind === 'subscription' ? colors.blue[300] : colors.cyan[300]} />
                        <Text fontSize="12px" color={CHAT_THEME.textPrimary} fontWeight="600" noOfLines={1}>{s.item}</Text>
                        <Text fontSize="11px" color={CHAT_THEME.textTertiary}>×{s.count}</Text>
                      </HStack>
                      <Text fontSize="13px" fontWeight="700" color={CHAT_THEME.textPrimary}>{rub(s.amount_rub)}</Text>
                    </HStack>
                  ))}
                </VStack>
              ) : (
                <Text fontSize="12px" color={CHAT_THEME.textTertiary} py={6} textAlign="center">
                  Продаж за период не было
                </Text>
              )}
            </ChartCard>

            <ChartCard label="Тарифы (активные пользователи)" hint={`MRR ${rub(fin.mrr_rub)}`}>
              <VStack align="stretch" spacing={1.5}>
                {plans.map((p) => (
                  <HStack key={p.plan} justify="space-between" p={2.5} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover}>
                    <HStack spacing={2} minW={0}>
                      <Text fontSize="12px" color={CHAT_THEME.textPrimary} fontWeight="600">{p.plan}</Text>
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary}>{rub(p.price_rub)}/мес</Text>
                    </HStack>
                    <HStack spacing={3}>
                      <Text fontSize="12px" color={CHAT_THEME.textSecondary}>{fmt(p.users)} чел.</Text>
                      <Text fontSize="13px" fontWeight="700" color={CHAT_THEME.textPrimary}>{rub(p.mrr_rub)}</Text>
                    </HStack>
                  </HStack>
                ))}
              </VStack>
            </ChartCard>
          </SimpleGrid>

          {/* ── ПОЛЬЗОВАТЕЛИ И АКТИВНОСТЬ ───────────────────────────────── */}
          <Text {...MICRO_LABEL_SX} color={CHAT_THEME.textSecondary} pt={1}>Пользователи и активность</Text>

          <SimpleGrid columns={{ base: 1, sm: 2, md: 4 }} spacing={3}>
            <StatTile label="Всего в базе" value={fmt(uTotals.total)} icon={FiUsers} accent={colors.blue[300]}
              sub={`${fmt(uTotals.verified)} с подтверждённой почтой`} />
            <StatTile label="Активных за период" value={fmt(fin.active_users)} icon={FiActivity} accent={colors.cyan[300]}
              sub={`конверсия ${pct(fin.conversion_pct)}`} />
            <StatTile label="Платящих" value={fmt(fin.paying_customers)} icon={FiCreditCard} accent={colors.iris[300]}
              sub={`на тарифе: ${fmt(uTotals.paying)}`} />
            <StatTile label="ARPU / ARPPU" value={`${rub(fin.arpu_rub)}`} icon={FiPercent} accent={colors.violet[300]}
              sub={`на платящего ${rub(fin.arppu_rub)}`} />
          </SimpleGrid>

          {activity.length > 0 && (
            <ChartCard label="Активные пользователи и регистрации по дням">
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={activity} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
                  <defs>
                    <linearGradient id="admDau" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colors.cyan[500]} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={colors.cyan[500]} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.surface.tint3} />
                  <XAxis dataKey="label" tickFormatter={shortDay} tick={{ fontSize: 10, fill: colors.fg[4] }} />
                  <YAxis tick={{ fontSize: 10, fill: colors.fg[4] }} allowDecimals={false} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: colors.border.medium }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area name="Активные" type="monotone" dataKey="active" stroke={colors.cyan[500]} strokeWidth={2} fill="url(#admDau)" />
                  <Bar name="Регистрации" dataKey="signups" fill={colors.blue[500]} radius={[4, 4, 0, 0]} barSize={10} />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>
          )}

          <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={4}>
            <ChartCard label="Активность по часам суток (UTC)" hint="запросы">
              <ResponsiveContainer width="100%" height={190}>
                <BarChart data={hourly} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.surface.tint3} vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: colors.fg[4] }} interval={1} />
                  <YAxis tick={{ fontSize: 10, fill: colors.fg[4] }} allowDecimals={false} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: colors.border.medium }} />
                  <Bar dataKey="requests" name="Запросы" fill={colors.iris[500]} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard label="Активность по дням недели" hint="запросы">
              <ResponsiveContainer width="100%" height={190}>
                <BarChart data={weekday} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.surface.tint3} vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: colors.fg[3] }} />
                  <YAxis tick={{ fontSize: 10, fill: colors.fg[4] }} allowDecimals={false} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: colors.border.medium }} />
                  <Bar dataKey="requests" name="Запросы" fill={colors.cyan[500]} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </SimpleGrid>

          {topUsers.length > 0 && (
            <ChartCard label="Топ пользователей" hint="доход · себестоимость · прибыль за период">
              <VStack align="stretch" spacing={1.5}>
                {topUsers.map((u, i) => (
                  <HStack key={u.id} justify="space-between" p={2.5} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover} gap={3}>
                    <HStack spacing={2.5} minW={0} flex="1">
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontFamily="mono" w="18px" flexShrink={0}>
                        {i + 1}
                      </Text>
                      <Text fontSize="12px" color={CHAT_THEME.textPrimary} noOfLines={1}>{u.email}</Text>
                      <Badge {...GHOST_BADGE_BLUE_SX} borderRadius="full" px={2} fontSize="9.5px" textTransform="none" flexShrink={0}>
                        {u.plan}
                      </Badge>
                    </HStack>
                    <HStack spacing={3} flexShrink={0}>
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary}>{fmt(u.requests)} зпр.</Text>
                      <Text fontSize="11px" color={colors.success}>{rub(u.revenue_rub)}</Text>
                      <Text fontSize="11px" color={colors.warning}>−{rub(u.cost_rub)}</Text>
                      <Text fontSize="12.5px" fontWeight="700" w="86px" textAlign="right"
                        color={u.profit_rub >= 0 ? colors.success : colors.error}>
                        {rub(u.profit_rub)}
                      </Text>
                    </HStack>
                  </HStack>
                ))}
              </VStack>
            </ChartCard>
          )}

          {/* ── ПОТРЕБЛЕНИЕ ─────────────────────────────────────────────── */}
          <Text {...MICRO_LABEL_SX} color={CHAT_THEME.textSecondary} pt={1}>Потребление</Text>

          <SimpleGrid columns={{ base: 1, sm: 2, md: 4 }} spacing={3}>
            <StatTile label="Запросов" value={fmt(totals.requests)} icon={FiActivity} accent={colors.blue[300]} />
            <StatTile label="Кредитов потрачено" value={fmt(totals.credits)} icon={FiZap} accent={colors.iris[300]} />
            <StatTile label="Ср. за запрос" value={fmt(totals.avg_credits_per_request)} icon={FiRepeat} accent={colors.cyan[300]} />
            <StatTile label="Флагов абьюза" value={fmt(flags.length)} icon={FiAlertTriangle}
              accent={flags.length ? colors.warning : colors.violet[300]} />
          </SimpleGrid>

          {series.length > 0 && (
            <ChartCard label="Траты по дням (кредиты)">
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={series} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
                  <defs>
                    <linearGradient id="admSpend" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colors.blue[500]} stopOpacity={0.45} />
                      <stop offset="100%" stopColor={colors.blue[500]} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.surface.tint3} />
                  <XAxis dataKey="day" tickFormatter={shortDay} tick={{ fontSize: 10, fill: colors.fg[4] }} />
                  <YAxis tick={{ fontSize: 10, fill: colors.fg[4] }} />
                  <Tooltip content={<ChartTip unit=" кр" />} cursor={{ stroke: colors.glass.borderHi, strokeWidth: 1 }} />
                  <Area type="monotone" dataKey="credits" stroke={colors.blue[500]} strokeWidth={2} fill="url(#admSpend)" />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>
          )}

          {(byModel.length > 0 || byAgent.length > 0) && (
            <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={4}>
              {byModel.length > 0 && (
                <ChartCard label="По моделям (кредиты)">
                  <HBar data={byModel} color={colors.iris[500]} />
                </ChartCard>
              )}
              {byAgent.length > 0 && (
                <ChartCard label="По типам операций (кредиты)">
                  <HBar data={byAgent} color={colors.cyan[500]} />
                </ChartCard>
              )}
            </SimpleGrid>
          )}

          {topRequests.length > 0 && (
            <ChartCard label="Самые дорогие запросы">
              <VStack align="stretch" spacing={1.5}>
                {topRequests.map((r, i) => (
                  <HStack key={`${r.model}-${i}`} justify="space-between" p={2.5} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover}>
                    <HStack spacing={2} minW={0}>
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontFamily="mono" w="18px">{i + 1}</Text>
                      <Text fontSize="12px" color={CHAT_THEME.textSecondary} fontFamily="mono" noOfLines={1}>
                        {shortModel(r.model)}
                      </Text>
                    </HStack>
                    <HStack spacing={3} flexShrink={0}>
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary}>{fmt(r.tokens)} т.</Text>
                      <Text fontSize="13px" fontWeight="700" color={CHAT_THEME.textPrimary}>{fmt(r.credits)} кр</Text>
                    </HStack>
                  </HStack>
                ))}
              </VStack>
            </ChartCard>
          )}

          {flags.length > 0 && (
            <ChartCard label="Флаги абьюза" hint={`${flags.length} за всё время`}>
              <VStack align="stretch" spacing={1.5}>
                {flags.slice(0, 8).map((f, i) => (
                  <HStack key={`${f.user_id}-${i}`} justify="space-between" p={2.5} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover}>
                    <HStack spacing={2} minW={0}>
                      <Icon as={FiAlertTriangle} boxSize={3.5} color={colors.warning} flexShrink={0} />
                      <Text fontSize="11.5px" color={CHAT_THEME.textSecondary} fontFamily="mono" noOfLines={1}>
                        {f.user_id}
                      </Text>
                    </HStack>
                    <HStack spacing={2} flexShrink={0}>
                      <Icon as={FiClock} boxSize={3} color={CHAT_THEME.textTertiary} />
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary}>
                        {String(f.created_at || '').slice(0, 16).replace('T', ' ')}
                      </Text>
                    </HStack>
                  </HStack>
                ))}
              </VStack>
            </ChartCard>
          )}
        </>
      )}
    </VStack>
  );
}
