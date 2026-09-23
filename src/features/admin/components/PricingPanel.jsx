import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  HStack,
  Icon,
  IconButton,
  Input,
  SimpleGrid,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiCheck, FiEdit2, FiTrash2, FiX } from '@shared/icons';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, INPUT_BASE } from '@theme/glass';
import { GHOST_BUTTON_BLUE_SX, MICRO_LABEL_SX } from '@theme/styles';
import { Skeleton } from '@shared/feedback/Skeleton';
import StateCard from '@shared/feedback/StateCard';
import Pager from '@shared/controls/Pager';
import AppSelect from '@shared/controls/AppSelect';
import { useAppToast } from '@shared/hooks/useAppToast';
import {
  deleteAdminPricing,
  getAdminPricing,
  getAdminReconcile,
  putAdminPricing,
} from '@api/admin';

const EMPTY = { provider: '', model_id: '', price_in_rub_per_1k: '', price_out_rub_per_1k: '' };
const TH_SX = { ...MICRO_LABEL_SX, borderBottom: `1px solid ${colors.border.subtle}`, pb: 2 };
const PAGE_SIZE = 20;
const DEFAULT_PROVIDERS = ['gigachat', 'openrouter', 'routerai'];
const SYNC_LEVEL_COLOR = { normal: 'green', warning: 'yellow', critical: 'red' };

// Цена в ячейку: у явно заданных — точное значение; у остальных — «≈<эффективная>»
// (цена по классу/умолчанию, которая реально спишется). Так НИ ОДНА модель не
// выглядит «нетарифицируемой». 0 показываем как есть (эмбеддинги: выхода нет → 0).
const priceText = (p, explicitKey, effKey) => {
  if (p.priced) return formatPrice(p[explicitKey]);
  const eff = p[effKey];
  return eff == null ? '—' : `≈${formatPrice(eff)}`;
};

// Провайдер из идентификатора модели: «ai21/…»/«openai/…» → префикс; «gigachat:…» →
// до двоеточия; «GigaChat…» без разделителя — по имени. Фолбэк, если бэкенд не
// прислал владельца (row.provider) — им пользуемся в первую очередь.
function providerOf(id) {
  if (!id) return '—';
  if (id.includes(':')) return id.split(':')[0];
  if (id.includes('/')) return id.split('/')[0];
  if (/gigachat/i.test(id)) return 'gigachat';
  return '—';
}
const provOf = (p) => p.provider || providerOf(p.model_id);
const pricingKey = (p) => `${p.provider || ''}:${p.model_id}`;

const formatPrice = (value) => {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 10 }).format(number);
};

const freshnessText = (seconds) => {
  if (!Number.isFinite(seconds)) return 'нет подтверждённой синхронизации';
  if (seconds < 3600) return `обновлено ${Math.max(1, Math.floor(seconds / 60))} мин назад`;
  if (seconds < 86400) return `обновлено ${Math.floor(seconds / 3600)} ч назад`;
  return `обновлено ${Math.floor(seconds / 86400)} дн. назад`;
};

export default function PricingPanel() {
  const [pricing, setPricing] = useState(null);
  const [pricingSync, setPricingSync] = useState(null);
  const [reconcile, setReconcile] = useState(null);
  const [reconcileError, setReconcileError] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [editingKey, setEditingKey] = useState(null);
  const [pendingDeleteKey, setPendingDeleteKey] = useState(null);
  const [providerFilter, setProviderFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useAppToast();
  const formRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    // list_pricing уже возвращает ВЕСЬ каталог (цены + модели без цены), поэтому
    // отдельный запрос доступных моделей не нужен.
    const [pricingResult, reconcileResult] = await Promise.allSettled([
      getAdminPricing(),
      getAdminReconcile('30d'),
    ]);
    const p = pricingResult.status === 'fulfilled' ? pricingResult.value : null;
    const r = reconcileResult.status === 'fulfilled' ? reconcileResult.value : null;
    setPricing(p?.pricing || []);
    setPricingSync(p?.pricing_sync || null);
    setReconcile(r);
    setReconcileError(reconcileResult.status === 'rejected');
    setError(!p);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const startEdit = (p) => {
    setForm({
      provider: p.provider || '',
      model_id: p.model_id,
      price_in_rub_per_1k: p.price_in_rub_per_1k ?? '',
      price_out_rub_per_1k: p.price_out_rub_per_1k ?? '',
    });
    setEditingKey(pricingKey(p));
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const cancelEdit = () => {
    setForm(EMPTY);
    setEditingKey(null);
  };

  const save = async () => {
    if (!form.provider || !form.model_id) return;
    const priceIn = Number(form.price_in_rub_per_1k);
    const priceOut = Number(form.price_out_rub_per_1k);
    if (!Number.isFinite(priceIn) || priceIn < 0 || !Number.isFinite(priceOut) || priceOut < 0) {
      toast({ title: 'Цена должна быть неотрицательным числом', status: 'warning', duration: 2500 });
      return;
    }
    setBusy(true);
    try {
      await putAdminPricing({
        provider: form.provider,
        model_id: form.model_id,
        price_in_rub_per_1k: priceIn,
        price_out_rub_per_1k: priceOut,
      });
      toast({ title: editingKey ? 'Цена обновлена' : 'Цена сохранена', status: 'success', duration: 1500 });
      cancelEdit();
      await load();
    } catch {
      toast({ title: 'Ошибка', status: 'error', duration: 2000 });
    } finally {
      setBusy(false);
    }
  };

  const del = async (p) => {
    setBusy(true);
    try {
      await deleteAdminPricing(p.model_id, p.provider || '');
      toast({ title: 'Цена удалена (действует fallback)', status: 'info', duration: 1800 });
      setPendingDeleteKey(null);
      if (editingKey === pricingKey(p)) cancelEdit();
      await load();
    } catch {
      toast({ title: 'Не удалось удалить', status: 'error', duration: 2000 });
    } finally {
      setBusy(false);
    }
  };

  // pricing уже содержит весь каталог → провайдеры и id для автокомплита берём из него.
  const modelIds = useMemo(() => Array.from(new Set((pricing || []).map((p) => p.model_id))), [pricing]);
  const providers = useMemo(() => {
    const set = new Set();
    (pricing || []).forEach((p) => set.add(provOf(p)));
    set.delete('—'); // «неизвестный» провайдер в фильтр не выносим
    return Array.from(new Set([...DEFAULT_PROVIDERS, ...set])).sort();
  }, [pricing]);
  const filtered = useMemo(
    () =>
      providerFilter === 'all'
        ? pricing || []
        : (pricing || []).filter((p) => provOf(p) === providerFilter),
    [pricing, providerFilter],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const paged = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  if (loading) {
    return (
      <VStack align="stretch" spacing={3} aria-busy="true">
        <Skeleton h="88px" radius={borderRadius.md} />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} h="44px" radius={borderRadius.sm} />
        ))}
      </VStack>
    );
  }

  if (error) {
    return <StateCard variant="error" message="Не удалось загрузить цены" onRetry={load} />;
  }

  return (
    <VStack align="stretch" spacing={4}>
      {pricingSync?.providers?.length > 0 && (
        <Box {...GLASS_SURFACE} borderRadius={borderRadius.md} p={3} role="region" aria-label="Статус свежести тарифов">
          <Text {...MICRO_LABEL_SX} mb={2}>Свежесть тарифов</Text>
          <SimpleGrid columns={{ base: 1, sm: 3 }} spacing={2}>
            {pricingSync.providers.map((item) => (
              <Box key={item.provider} p={2.5} borderRadius={borderRadius.sm} bg={CHAT_THEME.panelHover} minW={0}>
                <HStack justify="space-between" spacing={2} align="start">
                  <Text fontSize="12px" fontWeight="600" textTransform="capitalize" noOfLines={1}>
                    {item.provider}
                  </Text>
                  <Badge colorScheme={SYNC_LEVEL_COLOR[item.level] || 'yellow'} flexShrink={0}>
                    {item.level}
                  </Badge>
                </HStack>
                <Text mt={1} fontSize="11px" color={CHAT_THEME.textSecondary}>
                  {freshnessText(item.freshness_seconds)} · {item.synced_models || 0} моделей
                </Text>
                <Text mt={1} fontSize="11px" color={CHAT_THEME.textTertiary} noOfLines={2}>
                  {item.next_action}
                </Text>
              </Box>
            ))}
          </SimpleGrid>
        </Box>
      )}
      {reconcile && (
        <HStack spacing={2} flexWrap="wrap" align="start">
          <Badge colorScheme={reconcile.healthy ? 'green' : 'red'} px={2} py={1}>
            маржа: {reconcile.healthy ? 'здоровая' : 'УБЫТОК'}
          </Badge>
          {typeof reconcile.actual_margin !== 'undefined' && (
            <Text fontSize="12px" color={CHAT_THEME.textSecondary} flex="1 1 12rem" minW={0} overflowWrap="anywhere">
              фактическая маржа ≈ {reconcile.actual_margin}
            </Text>
          )}
          {reconcile.status?.next_action && (
            <Text fontSize="12px" color={CHAT_THEME.textSecondary} maxW="100%">
              {reconcile.status.next_action}
            </Text>
          )}
          {reconcile.cost_guard && (
            <Text fontSize="12px" color={CHAT_THEME.textSecondary} maxW="100%">
              24ч: {Number(reconcile.cost_guard.raw_cost_rub || 0).toFixed(2)} ₽ · fallback {reconcile.cost_guard.fallback_pricing || 0} · budget-stop {reconcile.cost_guard.prompt_budget_stops || 0} · резервов {reconcile.cost_guard.active_reservations || 0}/{reconcile.cost_guard.expired_reservations || 0}
            </Text>
          )}
        </HStack>
      )}
      {reconcileError && (
        <Box
          role="alert"
          {...GLASS_SURFACE}
          borderRadius={borderRadius.sm}
          borderColor={colors.warningBorder}
          px={3}
          py={2}
        >
          <HStack justify="space-between" spacing={3} align="center" flexWrap="wrap">
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>
              Не удалось загрузить сверку себестоимости. Тарифы остаются доступны.
            </Text>
            <Button size="xs" variant="ghost" color={colors.accent.subtleText} onClick={load}>
              Повторить
            </Button>
          </HStack>
        </Box>
      )}

      <Box ref={formRef} p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}
        borderColor={editingKey ? colors.border.blue : undefined}>
        <HStack justify="space-between" mb={3}>
          <Text {...MICRO_LABEL_SX}>
            {editingKey ? `Редактирование: ${form.provider}/${form.model_id}` : 'Добавить / обновить цену модели (₽ за 1K токенов)'}
          </Text>
          {editingKey && (
            <Button size="xs" variant="ghost" color={CHAT_THEME.textSecondary} onClick={cancelEdit}>
              Отмена
            </Button>
          )}
        </HStack>
        <SimpleGrid columns={{ base: 1, sm: 2, lg: 5 }} spacing={2}>
          <AppSelect
            ariaLabel="Провайдер"
            placeholder="Провайдер"
            value={form.provider}
            onChange={(provider) => setForm({ ...form, provider })}
            isDisabled={!!editingKey}
            options={providers.map((provider) => ({ value: provider, label: provider }))}
          />
          <Input
            list="admin-model-ids" placeholder="model_id" value={form.model_id}
            onChange={(e) => setForm({ ...form, model_id: e.target.value })}
            aria-label="Model ID"
            isDisabled={!!editingKey} {...INPUT_BASE}
          />
          <Input
            type="number" min={0} step="0.01" placeholder="вход ₽/1K"
            value={form.price_in_rub_per_1k}
            aria-label="Вход, ₽ за 1K"
            onChange={(e) => setForm({ ...form, price_in_rub_per_1k: e.target.value })} {...INPUT_BASE}
          />
          <Input
            type="number" min={0} step="0.01" placeholder="выход ₽/1K"
            value={form.price_out_rub_per_1k}
            aria-label="Выход, ₽ за 1K"
            onChange={(e) => setForm({ ...form, price_out_rub_per_1k: e.target.value })} {...INPUT_BASE}
          />
          <Button onClick={save} isLoading={busy} {...GHOST_BUTTON_BLUE_SX}>
            {editingKey ? 'Обновить' : 'Сохранить'}
          </Button>
        </SimpleGrid>
        <datalist id="admin-model-ids">
          {modelIds.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        <Text fontSize="11px" color={CHAT_THEME.textTertiary} mt={2}>
          Выберите провайдера и начните вводить model_id — подсказка содержит {modelIds.length || '—'} моделей. «≈» — fallback-цена, которая применяется, пока точная ставка не задана.
        </Text>
      </Box>

      {pricing && pricing.length === 0 ? (
        <StateCard message="Реестр цен пуст — действуют fallback-цены" />
      ) : (
        <Box {...GLASS_SURFACE} borderRadius={borderRadius.md} p={4}>
          {/* Фильтр по провайдеру + счётчик */}
          <HStack justify="space-between" mb={3} flexWrap="wrap" gap={2}>
            <HStack spacing={2}>
              <Text {...MICRO_LABEL_SX}>Провайдер</Text>
              <AppSelect
                size="sm"
                maxW="200px"
                value={providerFilter}
                onChange={(provider) => { setProviderFilter(provider); setPage(0); }}
                ariaLabel="Фильтр по провайдеру"
                options={[
                  { value: 'all', label: `все (${(pricing || []).length})` },
                  ...providers.map((provider) => ({ value: provider, label: provider })),
                ]}
              />
            </HStack>
            <Text fontSize="12px" color={CHAT_THEME.textTertiary}>
              {filtered.length} моделей
            </Text>
          </HStack>

          <Box overflowX="auto" role="region" aria-label="Таблица тарифов по моделям" tabIndex={0}>
            <Table size="sm" variant="unstyled" minW="680px">
              <Thead>
                <Tr>
                  <Th {...TH_SX}>Модель</Th>
                  <Th {...TH_SX}>Провайдер</Th>
                  <Th {...TH_SX} isNumeric>Вход ₽/1K</Th>
                  <Th {...TH_SX} isNumeric>Выход ₽/1K</Th>
                  <Th {...TH_SX}>Класс</Th>
                  <Th {...TH_SX} textAlign="right">Действия</Th>
                </Tr>
              </Thead>
              <Tbody>
                {paged.map((p) => (
                  <Tr
                    key={pricingKey(p)}
                    transition="background 140ms ease"
                    bg={editingKey === pricingKey(p) ? 'rgba(45,91,255,0.08)' : undefined}
                    _hover={{ bg: 'rgba(140,160,255,0.05)' }}
                  >
                    <Td color={CHAT_THEME.textPrimary} fontSize="13px" fontFamily="mono" whiteSpace="normal" wordBreak="break-word">{p.model_id}</Td>
                    <Td>
                      <Badge fontSize="10px" bg={CHAT_THEME.panelHover} color={CHAT_THEME.textSecondary} textTransform="lowercase">
                        {provOf(p)}
                      </Badge>
                    </Td>
                    <Td color={p.priced ? CHAT_THEME.textSecondary : CHAT_THEME.textTertiary} isNumeric>
                      {priceText(p, 'price_in_rub_per_1k', 'effective_in_rub_per_1k')}
                    </Td>
                    <Td color={p.priced ? CHAT_THEME.textSecondary : CHAT_THEME.textTertiary} isNumeric>
                      {priceText(p, 'price_out_rub_per_1k', 'effective_out_rub_per_1k')}
                    </Td>
                    <Td color={CHAT_THEME.textTertiary}>{p.model_class || '—'}</Td>
                    <Td>
                      {pendingDeleteKey === pricingKey(p) ? (
                        <HStack spacing={1} justify="flex-end">
                          <Text fontSize="11px" color={colors.error}>Удалить?</Text>
                          <IconButton aria-label="Подтвердить" size="xs" variant="ghost" color={colors.error}
                            icon={<Icon as={FiCheck} />} isLoading={busy} onClick={() => del(p)} />
                          <IconButton aria-label="Отмена" size="xs" variant="ghost" color={CHAT_THEME.textSecondary}
                            icon={<Icon as={FiX} />} onClick={() => setPendingDeleteKey(null)} />
                        </HStack>
                      ) : (
                        <HStack spacing={1} justify="flex-end">
                          <IconButton aria-label={p.priced ? 'Изменить' : 'Задать цену'} size="xs" variant="ghost"
                            color={colors.accent.subtleText} icon={<Icon as={FiEdit2} />} onClick={() => startEdit(p)} />
                          {/* Удаление — только для явно заданных цен (у fallback удалять нечего). */}
                          {p.priced && (
                            <IconButton aria-label="Удалить" size="xs" variant="ghost" color={CHAT_THEME.textTertiary}
                              _hover={{ color: colors.error }} icon={<Icon as={FiTrash2} />}
                              onClick={() => setPendingDeleteKey(pricingKey(p))} />
                          )}
                        </HStack>
                      )}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Box>

          <Box mt={4}>
            <Pager page={safePage} pageCount={pageCount} onChange={setPage} />
          </Box>
        </Box>
      )}
    </VStack>
  );
}
