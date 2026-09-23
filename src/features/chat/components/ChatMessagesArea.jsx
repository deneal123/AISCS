import React, { Suspense, lazy } from 'react';
import { Box, Button, HStack, Icon, IconButton, Text, VStack, keyframes } from '@chakra-ui/react';
import { FiArchive, FiArrowDown, FiChevronDown, FiChevronUp, FiRefreshCw } from '@shared/icons';
import { colors, borderRadius, motion } from '@theme/tokens';
import ChatMessageItem from './ChatMessageItem';
import ChatEmptyState from './ChatEmptyState';
import StatusBanner from './StatusBanner';
import AgentActivityStrip from './AgentActivityStrip';
import { CHAT_SCROLLBAR_SX, CHAT_THEME } from '../constants/theme';
import { getDateLabel, isSameDay } from '../utils/messageGrouping';

const TracePanel = lazy(() => import('./trace/TracePanel'));

// «Живое» кольцо кнопки «к последнему»: пока идёт генерация, а пользователь
// отмотал ленту вверх, пульс подсказывает, что НИЖЕ прибывает новый ответ
// (сам стрип активности при этом уехал за пределы вьюпорта).
const scrollLivePulse = keyframes`
  0%   { box-shadow: 0 6px 20px rgba(0,0,0,0.45), 0 0 0 0 ${colors.accent.glow}; }
  70%  { box-shadow: 0 6px 20px rgba(0,0,0,0.45), 0 0 0 7px rgba(45,91,255,0); }
  100% { box-shadow: 0 6px 20px rgba(0,0,0,0.45), 0 0 0 0 rgba(45,91,255,0); }
`;

/** Разделитель дат между сообщениями (Сегодня / Вчера / дата). */
function DateSeparator({ label }) {
  if (!label) return null;
  return (
    <HStack my={5} spacing={3} align="center" aria-hidden="true">
      <Box flex="1" h="1px" bg={CHAT_THEME.panelBorder} />
      <Text
        fontSize="10.5px"
        fontWeight="600"
        letterSpacing="0.08em"
        textTransform="uppercase"
        color={CHAT_THEME.textTertiary}
        fontFamily="'JetBrains Mono', monospace"
        whiteSpace="nowrap"
      >
        {label}
      </Text>
      <Box flex="1" h="1px" bg={CHAT_THEME.panelBorder} />
    </HStack>
  );
}

/**
 * Отметка о том, что контекст выше этой линии свёрнут в резюме и уехал в
 * долговременную память. Без неё сжатие выглядит как «ничего не произошло»: модель
 * перестаёт видеть старые реплики, но в ленте они остаются на месте.
 */
function CompactSeparator({ summary = '' }) {
  const [open, setOpen] = React.useState(false);
  const hasSummary = Boolean(String(summary || '').trim());
  return (
    <VStack my={5} spacing={2} align="stretch">
      <HStack spacing={3} align="center">
        <Box flex="1" h="1px" bg={`linear-gradient(90deg, transparent, ${colors.spectral.amber}55)`} />
        <HStack
          as={hasSummary ? 'button' : 'div'}
          type={hasSummary ? 'button' : undefined}
          onClick={hasSummary ? () => setOpen((v) => !v) : undefined}
          spacing={1.5}
          px={2.5}
          py={1}
          borderRadius={borderRadius.sm}
          border={`1px solid ${colors.spectral.amber}44`}
          bg={`${colors.spectral.amber}0f`}
          whiteSpace="nowrap"
          cursor={hasSummary ? 'pointer' : 'default'}
          _hover={hasSummary ? { bg: `${colors.spectral.amber}1a` } : undefined}
          title={hasSummary ? 'Показать резюме свёрнутого диалога' : undefined}
        >
          <Icon as={FiArchive} boxSize={3} color={colors.spectral.amber} />
          <Text
            fontSize="10.5px"
            fontWeight="600"
            letterSpacing="0.06em"
            textTransform="uppercase"
            color={colors.spectral.amber}
            fontFamily="'JetBrains Mono', monospace"
          >
            Контекст сжат → долговременная память
          </Text>
          {hasSummary && (
            <Icon as={open ? FiChevronUp : FiChevronDown} boxSize={3.5} color={colors.spectral.amber} />
          )}
        </HStack>
        <Box flex="1" h="1px" bg={`linear-gradient(90deg, ${colors.spectral.amber}55, transparent)`} />
      </HStack>
      {open && hasSummary && (
        <Box
          mx="auto"
          maxW="720px"
          w="100%"
          p={3}
          borderRadius={borderRadius.sm}
          border={`1px solid ${colors.spectral.amber}33`}
          bg={`${colors.spectral.amber}08`}
        >
          <Text
            fontSize="10px"
            fontWeight="700"
            textTransform="uppercase"
            letterSpacing="0.06em"
            color={colors.spectral.amber}
            mb={1.5}
            fontFamily="'JetBrains Mono', monospace"
          >
            Резюме свёрнутого диалога
          </Text>
          <Text fontSize="12.5px" color={CHAT_THEME.textSecondary} whiteSpace="pre-wrap" lineHeight="1.6">
            {summary}
          </Text>
        </Box>
      )}
    </VStack>
  );
}

/** Скелетон истории: брендовые shimmer-строки, пока грузятся сообщения треда. */
function HistorySkeleton() {
  const ROWS = [
    { side: 'right', lines: 1, w: '46%' },
    { side: 'left', lines: 3, w: '78%' },
    { side: 'right', lines: 1, w: '38%' },
    { side: 'left', lines: 2, w: '64%' },
  ];
  return (
    <VStack spacing={6} align="stretch" w="100%" maxW="860px" mx="auto" aria-hidden="true" pt={2}>
      {ROWS.map((row, i) => (
        <Box key={i} display="flex" justifyContent={row.side === 'right' ? 'flex-end' : 'flex-start'} w="100%">
          <Box w={row.w} maxW={{ base: '96%', md: '80%' }}>
            {row.side === 'left' && (
              <HStack spacing={2.5} mb={2}>
                <Box className="skeleton" boxSize="28px" borderRadius={borderRadius.sm} />
                <Box className="skeleton" h="12px" w="90px" borderRadius="6px" />
              </HStack>
            )}
            <VStack align="stretch" spacing={2}>
              {Array.from({ length: row.lines }).map((_, li) => (
                <Box
                  key={li}
                  className="skeleton"
                  h="13px"
                  w={li === row.lines - 1 ? '70%' : '100%'}
                  borderRadius="7px"
                />
              ))}
            </VStack>
          </Box>
        </Box>
      ))}
    </VStack>
  );
}

/** Скролл-область сообщений: баннеры состояния, пустое состояние, список сообщений + трейс. */
/**
 * Лента сообщений. МЕМОИЗИРОВАНА (см. export внизу): страница-контейнер
 * перерисовывается на любое своё состояние — открытие дровера/шторки, ввод, настройки.
 * Без memo лента на каждую такую перерисовку пере-сверяла ВЕСЬ список сообщений
 * (O(N) реконсиляции) — ровно во время 300ms слайд-анимации дровера, отчего шторки,
 * выдвигающиеся виджеты и списки заметно тормозили. Пропсы держим референсно
 * стабильными (useCallback/useMemo у вызывающего), иначе memo бесполезна.
 */
function ChatMessagesArea({
  scrollRef,
  endRef,
  handleScroll,
  atBottom,
  scrollToBottom,
  registerContentRef,
  error,
  providerStatus,
  connectionState,
  visibleMessages,
  isHistoryLoading,
  historyError = false,
  onRetryHistory,
  lastUsedModel,
  availableModels,
  copyMessage,
  regenerateMessage,
  editMessage,
  onFeedback,
  onRunMode,
  isLoading,
  compactedAfterId = null,
  compactedSummary = '',
  showTracePanel,
  traceSessionByAnchor,
  tracePanelsExpanded,
  isCompactTrace,
  onTraceToggle,
  currentJob,
  activeTraceSession,
  onCancelJob,
  personas,
  personaIds,
  onPersonaIdsChange,
  onboarding,
  onOpenWork,
}) {
  // Скролл-поведение (прилипание/кнопка) целиком управляется хуком
  // useChatAutoScroll в контейнере — здесь только потребляем пропсы.
  const showScrollBtn = !atBottom && visibleMessages.length > 0;
  // Генерация идёт, а лента отмотана вверх → под кнопкой копится новый ответ.
  const liveBelow = showScrollBtn && isLoading;

  return (
    <Box position="relative" flex="1" minH="0" display="flex" flexDirection="column">
      {/* Плавающие статус-баннеры — оверлей поверх ленты (absolute), чтобы их
          появление/исчезновение НЕ дёргало layout сообщений (раньше пушили ленту). */}
      {(error || providerStatus.unavailable || connectionState === 'connecting') && (
        <Box
          position="absolute"
          top={0}
          left={0}
          right={0}
          zIndex={3}
          px={{ base: 3, md: 6, lg: 8 }}
          pt={2}
          pointerEvents="none"
        >
          <VStack spacing={2} align="stretch" maxW="860px" mx="auto" sx={{ '& > *': { pointerEvents: 'auto' } }}>
            {error && <StatusBanner status="error">{error}</StatusBanner>}
            {providerStatus.unavailable && (
              <StatusBanner status="warning">
                Сервис моделей сейчас недоступен. Проверьте API-ключ и доступ к провайдеру.
                {providerStatus.error ? ` Детали: ${providerStatus.error}` : ''}
              </StatusBanner>
            )}
            {connectionState === 'connecting' && (
              <StatusBanner status="info">Подключаемся к каналу сообщений…</StatusBanner>
            )}
          </VStack>
        </Box>
      )}
      <Box
        ref={scrollRef}
        onScroll={handleScroll}
        flex="1"
        minH="0"
        overflowY="auto"
        px={{ base: 3, md: 6, lg: 8 }}
        pt={{ base: 5, md: 8 }}
        pb={{ base: 6, md: 8 }}
        sx={CHAT_SCROLLBAR_SX}
      >
        {visibleMessages.length === 0 && isHistoryLoading ? (
          <HistorySkeleton />
        ) : visibleMessages.length === 0 && historyError ? (
          <VStack spacing={3} maxW="420px" mx="auto" pt={{ base: 16, md: 24 }} textAlign="center">
            <Text fontSize="15px" fontWeight="600" color={CHAT_THEME.textSecondary}>
              Не удалось загрузить историю чата
            </Text>
            <Text fontSize="13px" color={CHAT_THEME.textTertiary} lineHeight="1.5">
              Проверьте соединение и повторите — сообщения не потеряны.
            </Text>
            <Button
              size="sm"
              leftIcon={<Icon as={FiRefreshCw} />}
              onClick={onRetryHistory}
              borderRadius={borderRadius.md}
              bg={CHAT_THEME.accentSoft}
              border={`1px solid ${colors.accent.subtleBorder}`}
              color={colors.blue[300]}
              fontWeight="600"
              _hover={{ bg: colors.accent.hoverSoft, color: 'white', borderColor: colors.accent.base }}
            >
              Повторить
            </Button>
          </VStack>
        ) : visibleMessages.length === 0 ? (
          <ChatEmptyState personas={personas} personaIds={personaIds} onPersonaIdsChange={onPersonaIdsChange} onboarding={onboarding} />
        ) : (
          <VStack ref={registerContentRef} spacing={0} align="stretch" w="100%" maxW="860px" mx="auto">
            {visibleMessages.map((message, idx) => {
              const prev = visibleMessages[idx - 1];
              const isLast = idx === visibleMessages.length - 1;
              // Первое сообщение в «серии» (сменился отправитель) — показываем шапку
              // ассистента; внутри серии — схлопываем и уплотняем вертикальный ритм.
              const isFirstInGroup = !prev || prev.type !== message.type;
              const showDate = !prev || !isSameDay(prev.timestamp, message.timestamp);
              const topGap = idx === 0 ? 0 : (isFirstInGroup ? 6 : 2);
              // Граница сжатия: всё, что ВЫШЕ, модель больше не видит целиком — оно
              // свёрнуто в резюме. Отметку ставим перед первым сообщением после сжатия.
              const showCompacted = Boolean(prev) && compactedAfterId != null
                && String(prev.id) === String(compactedAfterId);
              return (
                <React.Fragment key={`msg_block_${message.id}`}>
                  {showCompacted && <CompactSeparator summary={compactedSummary} />}
                  {showDate && <DateSeparator label={getDateLabel(message.timestamp)} />}
                  <Box mt={showDate ? 0 : topGap}>
                    <ChatMessageItem
                      message={message}
                      isLastMessage={isLast}
                      isFirstInGroup={isFirstInGroup}
                      lastUsedModel={lastUsedModel}
                      availableModels={isLast ? availableModels : undefined}
                      copyMessage={copyMessage}
                      regenerateMessage={regenerateMessage}
                      editMessage={editMessage}
                      onFeedback={onFeedback}
                      onOpenWork={onOpenWork}
                      // isLoading нужен только действиям ПОСЛЕДНЕГО сообщения —
                      // не транслируем смену loading во все memo-элементы списка.
                      isLoading={isLast ? isLoading : false}
                    />
                  </Box>
                  {showTracePanel && message.type === 'user' && traceSessionByAnchor.get(message.id)
                    ? (
                      <Box mt={3}>
                        <Suspense fallback={<Box h="24px" />}>
                          <TracePanel
                            sessions={[traceSessionByAnchor.get(message.id)]}
                            expandedMap={tracePanelsExpanded}
                            isCompactTrace={isCompactTrace}
                            onToggleExpanded={onTraceToggle}
                            onRunMode={onRunMode
                              ? (offer) => onRunMode(
                                  offer,
                                  message.content,
                                  message.id,
                                  traceSessionByAnchor.get(message.id)?.id,
                                )
                              : undefined}
                            isLoading={isLoading}
                          />
                        </Suspense>
                      </Box>
                    )
                    : null}
                </React.Fragment>
              );
            })}

            {/* Сжатие только что сработало и НОВОГО сообщения ещё нет → разделитель
                показываем в хвосте (над последним сообщением визуально), не дожидаясь
                следующей реплики. Когда придёт новое сообщение, сработает inline-ветка
                выше, и это условие станет ложным (дубля не будет). */}
            {compactedAfterId != null
              && visibleMessages.length > 0
              && String(visibleMessages[visibleMessages.length - 1].id) === String(compactedAfterId)
              && <CompactSeparator summary={compactedSummary} />}

            {currentJob?.status === 'processing' && (
              <AgentActivityStrip
                session={activeTraceSession}
                onCancel={() => onCancelJob(currentJob?.celeryTaskId)}
              />
            )}
            <Box ref={endRef} />
          </VStack>
        )}
      </Box>

      {/* Плавающая кнопка «к последнему сообщению» (появляется при прокрутке вверх).
          Во время генерации, когда лента отмотана, кнопка «оживает» пульсом и
          меняет подпись — так и зрячий, и screen-reader-пользователь понимают,
          что ниже прибывает новый ответ, а не просто «вы не внизу». */}
      <IconButton
        aria-label={liveBelow ? 'Новый ответ ниже — прокрутить вниз' : 'Прокрутить к последнему сообщению'}
        icon={<FiArrowDown />}
        onClick={scrollToBottom}
        position="absolute"
        bottom="16px"
        right={{ base: '16px', md: '28px' }}
        size="sm"
        borderRadius={borderRadius.full}
        bg={CHAT_THEME.inputStickyBg}
        color={colors.blue[300]}
        border={`1px solid ${liveBelow ? colors.accent.base : colors.accent.subtleBorder}`}
        boxShadow="0 6px 20px rgba(0,0,0,0.45)"
        backdropFilter="blur(12px)"
        _hover={{ bg: CHAT_THEME.panelActive, color: 'white', borderColor: colors.accent.base }}
        opacity={showScrollBtn ? 1 : 0}
        pointerEvents={showScrollBtn ? 'auto' : 'none'}
        visibility={showScrollBtn ? 'visible' : 'hidden'}
        transform={showScrollBtn ? 'translateY(0) scale(1)' : 'translateY(8px) scale(0.9)'}
        transition={`all 180ms ${motion.easeOut}`}
        animation={liveBelow ? `${scrollLivePulse} 1.8s ${motion.easeOut} infinite` : undefined}
        sx={{ '@media (prefers-reduced-motion: reduce)': { animation: 'none !important' } }}
        zIndex={3}
      />
    </Box>
  );
}

export default React.memo(ChatMessagesArea);
