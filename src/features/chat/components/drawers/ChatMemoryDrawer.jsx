import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Box,
  Button,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  Flex,
  HStack,
  Icon,
  IconButton,
  Input,
  InputGroup,
  InputRightElement,
  Spinner,
  Text,
  useDisclosure,
  VStack,
} from '@chakra-ui/react';
import { FiAlertCircle, FiArchive, FiChevronDown, FiChevronUp, FiCircle, FiCpu, FiLayers, FiPlus, FiSearch, FiStar, FiTrash2, FiUser, FiX } from '@shared/icons';
import { colors, borderRadius, typography } from '@theme/tokens';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_OVERLAY_PROPS, DRAWER_RADIAL_BG, DRAWER_CONTENT_BG } from '@theme/drawer';
import { GLASS_SURFACE_STRONG } from '@theme/glass';
import { CHAT_SCROLLBAR_SX, CHAT_THEME } from '../../constants/theme';

/**
 * Метаданные типов фактов (таксономия бэкенда) — только мягкие тинты
 * (tinted bg + colored text), без сплошных заливок и без красного. Неизвестные
 * типы (напр. legacy 'note') аккуратно падают на `general`.
 */
const FACT_TYPE_META = {
  identity: { label: 'Личность', icon: FiUser, color: colors.violet[300], softBg: 'rgba(180,92,255,0.12)', border: 'rgba(180,92,255,0.28)' },
  preference: { label: 'Предпочтение', icon: FiStar, color: colors.cyan[300], softBg: 'rgba(61,217,188,0.12)', border: 'rgba(61,217,188,0.28)' },
  context: { label: 'Контекст', icon: FiLayers, color: colors.iris[300], softBg: colors.accent.subtle, border: colors.accent.subtleBorder },
  constraint: { label: 'Ограничение', icon: FiAlertCircle, color: colors.spectral.amber, softBg: 'rgba(255,197,110,0.12)', border: 'rgba(255,197,110,0.28)' },
  general: { label: 'Общее', icon: FiCircle, color: colors.fg[4], softBg: colors.border.faint, border: colors.border.subtle },
};

// Сколько фактов видно в свёрнутом списке. Столько же показывает секция MemOS выше —
// панель не должна складываться по двум разным правилам.
const FACTS_PREVIEW = 5;

/** Русская плюрализация: forms = [ед., 2–4, много]. */
function pluralize(n, forms) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
  return forms[2];
}

/** Тип факта — мягкая mono-таблетка (рецепт TagPill, без солид-заливок). */
function TypeBadge({ meta }) {
  return (
    <Text
      as="span"
      display="inline-flex"
      alignItems="center"
      gap={1}
      px={2.5}
      py={1}
      borderRadius={borderRadius.full}
      fontSize="11px"
      fontWeight="600"
      fontFamily={typography.fontFamily.mono}
      color={meta.color}
      bg={meta.softBg}
      border={`1px solid ${meta.border}`}
    >
      <Icon as={meta.icon} boxSize="11px" />
      {meta.label}
    </Text>
  );
}

/**
 * Сводка памяти над списком: разбивка фактов по типам (из надёжного реестра
 * фактов) + опциональный объём семантической памяти MemOS, когда он ненулевой.
 * Даёт пользователю картину «что о нём знает ассистент» одним взглядом.
 */
function MemoryOverview({ facts, dashboard }) {
  const breakdown = useMemo(() => {
    const counts = {};
    for (const f of facts || []) {
      const type = FACT_TYPE_META[f?.fact_type] ? f.fact_type : 'general';
      counts[type] = (counts[type] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([type, count]) => ({ type, count, meta: FACT_TYPE_META[type] }))
      .sort((a, b) => b.count - a.count);
  }, [facts]);

  // Объём семантической памяти MemOS (сумма узлов по типам). Показываем строкой
  // только когда > 0 — иначе (community-режим/пусто) не вводим в заблуждение нулём.
  const memosTotal = useMemo(() => {
    const stats = dashboard?.statistics;
    if (!stats || typeof stats !== 'object') return 0;
    return Object.values(stats).reduce((sum, v) => sum + (Number(v) || 0), 0);
  }, [dashboard]);

  if (!breakdown.length) return null;

  return (
    <Box mb={4}>
      <Flex gap={1.5} flexWrap="wrap">
        {breakdown.map(({ type, count, meta }) => (
          <HStack
            key={type}
            spacing={1.5}
            px={2.5}
            py={1}
            borderRadius={borderRadius.full}
            bg={meta.softBg}
            border={`1px solid ${meta.border}`}
          >
            <Icon as={meta.icon} boxSize="11px" color={meta.color} />
            <Text as="span" fontSize="11px" fontWeight="600" color={colors.text.secondary}>
              {meta.label}
            </Text>
            <Text as="span" fontSize="11px" fontWeight="700" fontFamily={typography.fontFamily.mono} color={meta.color}>
              {count}
            </Text>
          </HStack>
        ))}
      </Flex>
      {memosTotal > 0 && (
        <Text mt={2} fontSize="11px" color={colors.text.tertiary} fontFamily={typography.fontFamily.mono}>
          MemOS · {memosTotal} {pluralize(memosTotal, ['запись', 'записи', 'записей'])} в семантической памяти
        </Text>
      )}
    </Box>
  );
}

/** Достать тексты воспоминаний MemOS из ответа дашборда (группы text/pref/tool/skill). */
function extractMemosMemories(dashboard) {
  if (!dashboard || typeof dashboard !== 'object') return [];
  const out = [];
  for (const group of ['text_mem', 'pref_mem', 'tool_mem', 'skill_mem']) {
    const cubes = dashboard[group];
    if (!Array.isArray(cubes)) continue;
    for (const cube of cubes) {
      for (const m of cube?.memories || []) {
        const text = typeof m === 'string' ? m : (m?.memory || m?.text || m?.content || m?.summary || '');
        if (text && String(text).trim()) out.push(String(text).trim());
      }
    }
  }
  return out;
}

/**
 * Раскрывающаяся секция семантической памяти MemOS: последние воспоминания
 * (саммери диалогов и извлечённые факты). По умолчанию показывает 5 последних,
 * можно раскрыть все. Скрыта, если MemOS пуст.
 */
function MemosSection({ dashboard }) {
  const [expanded, setExpanded] = useState(false);
  const memories = useMemo(() => extractMemosMemories(dashboard), [dashboard]);
  if (!memories.length) return null;
  const ordered = [...memories].reverse(); // свежие сверху
  const shown = expanded ? ordered : ordered.slice(0, 5);
  return (
    <Box mb={4} borderRadius={borderRadius.md} bg={CHAT_THEME.panelBg} border={`1px solid ${CHAT_THEME.panelBorder}`} overflow="hidden">
      <HStack
        as="button"
        w="100%"
        px={3}
        py={2.5}
        spacing={2}
        onClick={() => setExpanded((v) => !v)}
        _hover={{ bg: CHAT_THEME.panelHover }}
        transition="background 0.15s"
      >
        <Icon as={FiArchive} boxSize="13px" color={colors.spectral.amber} />
        <Text fontSize="12px" fontWeight="700" color={colors.text.primary}>
          Семантическая память MemOS
        </Text>
        <Text as="span" fontSize="11px" fontWeight="700" fontFamily={typography.fontFamily.mono} color={colors.spectral.amber}>
          {memories.length}
        </Text>
        <Icon as={expanded ? FiChevronUp : FiChevronDown} boxSize="14px" color={colors.text.tertiary} ml="auto" />
      </HStack>
      <VStack align="stretch" spacing={0} px={3} pb={2.5}>
        {shown.map((text, i) => (
          <Text
            key={i}
            fontSize="12.5px"
            color={colors.text.secondary}
            lineHeight="1.5"
            py={2}
            borderTop={`1px solid ${colors.border.faint}`}
          >
            {text}
          </Text>
        ))}
        {!expanded && ordered.length > 5 && (
          <Text fontSize="11px" color={colors.text.tertiary} pt={2} textAlign="center">
            …ещё {ordered.length - 5}, нажмите чтобы раскрыть
          </Text>
        )}
      </VStack>
    </Box>
  );
}

/**
 * Drawer долговременной памяти пользователя: список извлечённых фактов с
 * поиском и удалением. Источник — provider-agnostic API `/api/memory`
 * (работает одинаково поверх mem0 или MemOS).
 */
export default function ChatMemoryDrawer({ isOpen, onClose, memoryFacts, memoryDashboard, onSearch, onDeleteFact, onAddFact, onClearAll }) {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [addValue, setAddValue] = useState('');
  const [adding, setAdding] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [factsExpanded, setFactsExpanded] = useState(false);
  const clearDialog = useDisclosure();
  const cancelClearRef = useRef(null);
  const debounceRef = useRef(0);

  // Сколько записей в семантической памяти — нужно и для текста подтверждения, и для
  // решения показывать ли кнопку: память бывает пустой в фактах, но полной в MemOS.
  const memosCount = useMemo(() => extractMemosMemories(memoryDashboard).length, [memoryDashboard]);
  const hasAnything = (memoryFacts?.length || 0) > 0 || memosCount > 0;

  // Без запроса — свежие факты сверху (updated_at desc, null → порядок вставки).
  // При поиске сохраняем порядок бэкенда (релевантность).
  const sortedFacts = useMemo(() => {
    const list = [...(memoryFacts || [])];
    if (query.trim()) return list;
    return list.sort((a, b) => {
      const ta = a.updated_at ? Date.parse(a.updated_at) || 0 : 0;
      const tb = b.updated_at ? Date.parse(b.updated_at) || 0 : 0;
      return tb - ta;
    });
  }, [memoryFacts, query]);

  // Список сворачивается до пяти записей — тем же приёмом, что и семантическая память
  // выше. При десятках фактов панель уезжала на несколько экранов, и всё, что стоит под
  // списком (в том числе очистка памяти), оказывалось за пределами видимого.
  //
  // ⚠️ Свёрнут по умолчанию, но НЕ спрятан: пять свежих фактов видно сразу, и «что обо
  // мне помнят» читается без единого клика. Полное сворачивание сэкономило бы ещё
  // немного места ценой главного содержимого панели.
  //
  // При поиске показываем всё: там список и так короткий, а урезать выдачу по запросу
  // значит скрыть ровно то, что человек искал.
  const searching = Boolean(query.trim());
  const factsCollapsible = !searching && sortedFacts.length > FACTS_PREVIEW;
  const shownFacts =
    factsCollapsible && !factsExpanded ? sortedFacts.slice(0, FACTS_PREVIEW) : sortedFacts;

  const handleAdd = useCallback(async () => {
    const text = addValue.trim();
    if (!text || !onAddFact) return;
    setAdding(true);
    try {
      await onAddFact(text);
      setAddValue('');
    } finally {
      setAdding(false);
    }
  }, [addValue, onAddFact]);

  const handleClearAll = useCallback(async () => {
    if (!onClearAll) return;
    setClearing(true);
    try {
      await onClearAll();
      clearDialog.onClose();
    } finally {
      setClearing(false);
    }
  }, [onClearAll, clearDialog]);

  // Сброс при закрытии: следующий заход начинается с полного списка и свёрнутого вида —
  // иначе однажды раскрытые полсотни фактов встречали бы человека каждое открытие.
  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setFactsExpanded(false);
    }
  }, [isOpen]);

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current); }, []);

  const runSearch = useCallback(async (value) => {
    if (!onSearch) return;
    setBusy(true);
    try {
      await onSearch(value);
    } finally {
      setBusy(false);
    }
  }, [onSearch]);

  const handleQueryChange = useCallback((e) => {
    const value = e.target.value;
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(value.trim()), 350);
  }, [runSearch]);

  const handleClearQuery = useCallback(() => {
    setQuery('');
    if (debounceRef.current) clearTimeout(debounceRef.current);
    runSearch('');
  }, [runSearch]);

  const handleDelete = useCallback(async (factId) => {
    if (!onDeleteFact) return;
    setDeletingId(factId);
    try {
      await onDeleteFact(factId);
    } finally {
      setDeletingId(null);
    }
  }, [onDeleteFact]);

  return (
    <Drawer isOpen={isOpen} placement="right" onClose={onClose} size="md">
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
      <DrawerContent bg={DRAWER_CONTENT_BG} borderLeft={`1px solid ${CHAT_THEME.panelBorder}`} sx={{ willChange: 'transform', backgroundImage: DRAWER_RADIAL_BG }}>
        <DrawerCloseButton aria-label="Закрыть память и контекст" mt={2} {...DRAWER_CLOSE_BUTTON_PROPS} />
        <DrawerHeader borderBottomWidth="1px" borderColor={colors.border.subtle} display="flex" alignItems="center" gap={2}>
          <Icon as={FiCpu} boxSize="18px" color={colors.iris[300]} />
          Долговременная память
        </DrawerHeader>
        <DrawerBody pt={4} sx={CHAT_SCROLLBAR_SX}>
          <Text fontSize="xs" color={colors.text.tertiary} mb={3}>
            Здесь сохраняются устойчивые факты: предпочтения, контекст проектов и важные договоренности.
            Память общая для всех ваших диалогов — не привязана к конкретному чату.
          </Text>

          {!query.trim() && (
            <MemoryOverview facts={memoryFacts} dashboard={memoryDashboard} />
          )}

          {!query.trim() && <MemosSection dashboard={memoryDashboard} />}

          {onAddFact && (
            <HStack mb={3} spacing={2}>
              <Input
                size="sm"
                value={addValue}
                onChange={(e) => setAddValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
                placeholder="Добавить факт вручную…"
                aria-label="Добавить факт вручную"
                bg={CHAT_THEME.inputBg}
                border={`1px solid ${CHAT_THEME.inputBorder}`}
                borderRadius={borderRadius.sm}
                color={colors.text.primary}
                _placeholder={{ color: colors.text.tertiary }}
                _focus={{ borderColor: CHAT_THEME.inputBorderFocus, boxShadow: 'none' }}
              />
              <IconButton
                aria-label="Добавить факт"
                icon={adding ? <Spinner size="xs" /> : <FiPlus />}
                size="sm"
                flexShrink={0}
                bg={CHAT_THEME.accent}
                color="white"
                borderRadius={borderRadius.sm}
                _hover={{ bg: CHAT_THEME.accentHover }}
                isDisabled={!addValue.trim() || adding}
                onClick={handleAdd}
              />
            </HStack>
          )}

          {onSearch && (
            <InputGroup size="sm" mb={4}>
              <Input
                value={query}
                onChange={handleQueryChange}
                placeholder="Поиск по памяти…"
                aria-label="Поиск по памяти"
                bg={CHAT_THEME.inputBg}
                border={`1px solid ${CHAT_THEME.inputBorder}`}
                borderRadius={borderRadius.sm}
                color={colors.text.primary}
                _placeholder={{ color: colors.text.tertiary }}
                _focus={{ borderColor: CHAT_THEME.inputBorderFocus, boxShadow: 'none' }}
              />
              <InputRightElement>
                {busy ? (
                  <Spinner size="xs" color={colors.blue[300]} />
                ) : query ? (
                  <IconButton aria-label="Очистить поиск" icon={<FiX />} size="xs" variant="ghost"
                    color={colors.text.tertiary} onClick={handleClearQuery} />
                ) : (
                  <Box color={colors.text.tertiary}><FiSearch /></Box>
                )}
              </InputRightElement>
            </InputGroup>
          )}

          {memoryFacts.length === 0 ? (
            <VStack spacing={3} py={10} px={4} textAlign="center">
              <Box
                boxSize="46px"
                borderRadius={borderRadius.md}
                bg={CHAT_THEME.accentSoft}
                border={`1px solid ${colors.accent.subtleBorder}`}
                display="flex"
                alignItems="center"
                justifyContent="center"
              >
                <Icon as={FiCpu} boxSize="22px" color={colors.blue[300]} />
              </Box>
              <Text color={colors.text.secondary} maxW="300px" lineHeight="1.5">
                {query
                  ? 'По запросу ничего не найдено.'
                  : 'Память пуста. Факты будут автоматически извлекаться из ваших разговоров.'}
              </Text>
            </VStack>
          ) : (
            <VStack spacing={3} align="stretch">
              {/* Строка счёта заодно и переключатель: отдельная кнопка «свернуть» рядом
                  с ней была бы вторым элементом про одно и то же. */}
              <HStack
                as={factsCollapsible ? 'button' : 'div'}
                spacing={1.5}
                onClick={factsCollapsible ? () => setFactsExpanded((v) => !v) : undefined}
                aria-expanded={factsCollapsible ? factsExpanded : undefined}
                _hover={factsCollapsible ? { color: colors.text.secondary } : undefined}
                color={colors.text.tertiary}
                transition="color 0.15s"
              >
                <Text fontSize="xs">
                  {memoryFacts.length} {pluralize(memoryFacts.length, ['факт', 'факта', 'фактов'])} {query ? 'найдено' : 'сохранено'}
                </Text>
                {factsCollapsible && (
                  <Icon as={factsExpanded ? FiChevronUp : FiChevronDown} boxSize="13px" />
                )}
              </HStack>
              {shownFacts.map((fact) => {
                const meta = FACT_TYPE_META[fact.fact_type] || FACT_TYPE_META.general;
                return (
                  <Box
                    key={fact.id}
                    p={3}
                    borderRadius={borderRadius.md}
                    bg={CHAT_THEME.panelBg}
                    border={`1px solid ${CHAT_THEME.panelBorder}`}
                    position="relative"
                    role="group"
                    opacity={fact.superseded ? 0.55 : 1}
                  >
                    <Box mb={2} pr={6}>
                      <TypeBadge meta={meta} />
                      {/* Есть более свежий факт с тем же ключом — этот в промпт НЕ идёт.
                          Не прячем: расхождение видно, только когда оба значения рядом,
                          а удалять — решение пользователя. Скрытая запись, про которую
                          неясно, влияет она или нет, необъяснима. */}
                      {fact.superseded && (
                        <Text as="span" ml={2} fontSize="10px" color={colors.text.tertiary}>
                          устарел — заменён свежим «{fact.fact_key}»
                        </Text>
                      )}
                    </Box>
                    <Text fontSize="sm" fontWeight="600" color={colors.text.primary} noOfLines={2}>
                      {fact.fact_key}
                    </Text>
                    <Text fontSize="sm" color={colors.text.secondary} mt={1} lineHeight="1.5">
                      {fact.fact_value}
                    </Text>
                    {fact.updated_at && (
                      <Text fontSize="xs" color={colors.text.tertiary} mt={1}>
                        {new Date(fact.updated_at).toLocaleDateString('ru')}
                      </Text>
                    )}
                    {onDeleteFact && (
                      <IconButton
                        aria-label="Удалить факт"
                        icon={deletingId === fact.id ? <Spinner size="xs" /> : <FiTrash2 />}
                        size="xs"
                        variant="ghost"
                        position="absolute"
                        top={2}
                        right={2}
                        color={colors.text.tertiary}
                        opacity={0}
                        _groupHover={{ opacity: 1 }}
                        _hover={{ color: colors.blue[300], bg: colors.accent.soft }}
                        isDisabled={deletingId === fact.id}
                        onClick={() => handleDelete(fact.id)}
                      />
                    )}
                  </Box>
                );
              })}
              {factsCollapsible && !factsExpanded && (
                <Text
                  as="button"
                  fontSize="11px"
                  color={colors.text.tertiary}
                  textAlign="center"
                  py={1}
                  _hover={{ color: colors.text.secondary }}
                  onClick={() => setFactsExpanded(true)}
                >
                  …ещё {sortedFacts.length - FACTS_PREVIEW}, нажмите чтобы раскрыть
                </Text>
              )}
            </VStack>
          )}

          {/* Полная очистка — внизу и только когда есть что стирать. Удалять по одному
              можно было и раньше, но при десятках записей это занятие, а не операция.
              Кнопка держится в стороне от обычных действий: она необратима. */}
          {onClearAll && hasAnything && !query.trim() && (
            <Box mt={6} pt={4} borderTop={`1px solid ${colors.border.faint}`}>
              <Button
                size="sm"
                variant="ghost"
                width="100%"
                leftIcon={<Icon as={FiTrash2} boxSize="14px" />}
                color={colors.text.tertiary}
                _hover={{ color: colors.spectral.amber, bg: 'rgba(255,197,110,0.10)' }}
                onClick={clearDialog.onOpen}
              >
                Очистить всю память
              </Button>
            </Box>
          )}
        </DrawerBody>
      </DrawerContent>

      <AlertDialog
        isOpen={clearDialog.isOpen}
        leastDestructiveRef={cancelClearRef}
        onClose={clearDialog.onClose}
        isCentered
      >
        <AlertDialogOverlay>
          <AlertDialogContent {...GLASS_SURFACE_STRONG} color={colors.text.primary}>
            <AlertDialogHeader fontSize="md">Очистить всю долговременную память?</AlertDialogHeader>
            <AlertDialogBody fontSize="sm" color={colors.text.secondary}>
              {/* Называем ОБЕ половины и их объём: «очистить память» без числа не даёт
                  понять, что именно исчезнет, а семантическая память не видна списком. */}
              Будут удалены {memoryFacts?.length || 0}{' '}
              {pluralize(memoryFacts?.length || 0, ['факт', 'факта', 'фактов'])}
              {memosCount > 0 && (
                <> и {memosCount} {pluralize(memosCount, ['запись', 'записи', 'записей'])} семантической памяти MemOS</>
              )}
              . Ассистент забудет их во всех диалогах. Отменить это будет нельзя — история
              переписки при этом останется на месте.
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelClearRef} onClick={clearDialog.onClose} size="sm" variant="ghost" isDisabled={clearing}>
                Отмена
              </Button>
              <Button onClick={handleClearAll} size="sm" ml={3} colorScheme="red" isLoading={clearing}>
                Очистить
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Drawer>
  );
}
