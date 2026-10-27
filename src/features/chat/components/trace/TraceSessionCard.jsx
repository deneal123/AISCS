import React, { memo, useMemo } from 'react';
import { Box, Collapse, HStack, Icon, Spinner, Progress, Text, VStack } from '@chakra-ui/react';
import { FiAlertCircle, FiCheckCircle, FiChevronDown, FiClock } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import TraceEventRow from './TraceEventRow';
import { getSessionStatus } from '../../utils/trace';
import { useTraceActivity } from '../../hooks/useTraceActivity';
import ModeOffer from '../ModeOffer';

function TraceDetails({ contained, expanded, offer, children }) {
  if (!contained) return <>{offer}<Collapse in={expanded} animateOpacity>{children}</Collapse></>;
  return <Box flex="1" minH={0} minW={0} overflowY="auto" overscrollBehavior="contain"
    role="region" aria-label="Этапы выполнения" tabIndex={0} hidden={!expanded && !offer}
    data-testid="workbench-trace-scroll"
    onKeyDown={(event) => {
      // Home/End принадлежат сфокусированному скроллеру, не странице позади
      // него. Клавиши внутри кнопок/полей предложения остаются их владельцу.
      if (event.target !== event.currentTarget || event.altKey || event.metaKey) return;
      if (event.key !== 'Home' && event.key !== 'End') return;
      event.preventDefault();
      event.currentTarget.scrollTop = event.key === 'Home' ? 0 : event.currentTarget.scrollHeight;
    }}
    sx={{ scrollbarGutter: 'stable' }}
    _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
    {offer}<Box hidden={!expanded}>{children}</Box>
  </Box>;
}

function TraceSessionCardComponent({ session, isCompactTrace, isExpanded, onToggleExpanded, onRunMode, isLoading, layout, stopHint = 'Можно остановить запрос кнопкой в поле сообщения.' }) {
  const contained = layout === 'workbench';
  const stepCount = (session.events || []).length;
  const stepLabel = { one: 'шаг', few: 'шага', many: 'шагов', other: 'шага' }[
    new Intl.PluralRules('ru-RU').select(stepCount)
  ];
  const { visibleTraceEvents, hiddenTraceEventsCount } = useMemo(() => {
    // Подряд идущие ОДИНАКОВЫЕ события схлопываем в одно со счётчиком: агент часто
    // вызывает один инструмент 9 раз подряд, и панель превращалась в стену повторов
    // «Вызван инструмент: search_knowledge_graph». Показываем «… ×9».
    const raw = session.events || [];
    const events = [];
    for (const e of raw) {
      const last = events[events.length - 1];
      if (last && last.title === e.title && last.detail === e.detail) {
        last._repeatCount = (last._repeatCount || 1) + 1;
      } else {
        events.push({ ...e });
      }
    }
    const visible = isCompactTrace ? events.slice(-6) : events;
    return {
      visibleTraceEvents: visible,
      hiddenTraceEventsCount: Math.max(0, events.length - visible.length),
    };
  }, [session.events, isCompactTrace]);

  const { isRunning, isError } = getSessionStatus(session.status);
  const activity = useTraceActivity(session);
  const waitingOffer = session.status === 'awaiting_confirmation'
    ? [...(session.events || [])].reverse().find((event) => event.offer)?.offer : null;
  // ⚠️ «Ход работы», а не «Ход рассуждения». Панель показывает ШАГИ ОБРАБОТКИ
  // (маршрутизация, сборка контекста, вызовы инструментов), а рассуждения модели — лишь
  // один из шагов и бывают не у всякой модели. Прежний заголовок обещал именно их:
  // человек видел «Ход рассуждения · 7 шагов» на модели без reasoning и справедливо
  // спрашивал, где размышления.
  const headerTitle = isRunning
    ? 'Готовлю ответ…'
    : session.status === 'awaiting_confirmation'
      ? 'Ожидаю ваше решение'
    : isError
      ? 'Не удалось подготовить ответ'
      : 'Ход работы';
  const borderColor = isError
    ? colors.errorBorder
    : isRunning
      ? colors.accent.subtleBorder
      : colors.glass.border;

  return (
    <Box
      w="100%"
      maxW={contained ? '100%' : '860px'}
      minH={0}
      display={contained ? 'flex' : undefined}
      flexDirection={contained ? 'column' : undefined}
      flex={contained && (isExpanded || waitingOffer) ? '1' : undefined}
      data-testid={contained ? 'workbench-trace-card' : undefined}
      borderRadius={borderRadius.md}
      border={`1px solid ${borderColor}`}
      bg={colors.surface.tint2}
      overflow="hidden"
      boxShadow={!contained && isRunning ? `0 10px 32px ${colors.accent.subtle}` : 'none'}
    >
      <HStack
        as="button"
        type="button"
        flexShrink={0}
        aria-expanded={isExpanded}
        aria-label={isRunning ? 'Ход работы: показать или скрыть этапы' : headerTitle}
        onClick={() => onToggleExpanded(!isExpanded)}
        w="100%"
        minH="44px"
        px={{ base: 3, md: 3.5 }}
        py={2.75}
        spacing={2}
        textAlign="left"
        transition="background 0.15s"
        _hover={{ bg: colors.surface.tint2 }}
        _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}
      >
        {isRunning ? (
          <Spinner size="xs" color={colors.iris[500]} flexShrink={0} label="Выполняется" />
        ) : (
          <Icon
            as={isError ? FiAlertCircle : waitingOffer ? FiClock : FiCheckCircle}
            color={isError ? colors.error : waitingOffer ? colors.iris[300] : colors.success}
            boxSize={4}
            flexShrink={0}
          />
        )}
        <Text fontSize="13px" fontWeight="650" color={colors.text.primary} minW={0} overflowWrap="anywhere">
          {headerTitle}
        </Text>
        <Text fontSize="11px" color={colors.text.tertiary} flexShrink={0} whiteSpace="nowrap">
          {stepCount} {stepLabel}
        </Text>
        {/* Текст запроса тут НЕ дублируем — он уже показан в шаге «Запрос принят». */}
        <Box flex="1" />
        <Icon
          as={FiChevronDown}
          color={colors.text.tertiary}
          boxSize={4}
          flexShrink={0}
          transform={isExpanded ? 'rotate(180deg)' : 'none'}
          transition="transform 0.2s"
        />
      </HStack>

      {isRunning && (
        <Box px={{ base: 3, md: 3.5 }} pb={2.75} flexShrink={0}>
          <HStack align="start" justify="space-between" spacing={2}>
            <Text role="status" aria-live="polite" fontSize="12px" color={colors.text.secondary} minW={0} overflowWrap="anywhere">
              {activity.label}
            </Text>
            <Text fontSize="11px" color={colors.text.tertiary} flexShrink={0} whiteSpace="nowrap" aria-hidden="true">
              {activity.elapsed}
            </Text>
          </HStack>
          {activity.stale && (
            <Text role="status" mt={2} fontSize="12px" color={colors.warning}>
              Нет новых статусов {activity.silence}. Выполнение может продолжаться, но его прогресс сейчас не подтверждён. {stopHint}
            </Text>
          )}
        </Box>
      )}

      <TraceDetails contained={contained} expanded={isExpanded} offer={waitingOffer && <Box px={{ base: 3, md: 4 }} pb={3}>
        <ModeOffer offer={waitingOffer} onRun={onRunMode} disabled={isLoading} />
      </Box>}>
        <Box px={{ base: 3, md: 4 }} pb={3.5} pt={2}>
          {isRunning && typeof session.progress?.percent === 'number' && (
            <Box pb={2.5} mb={1}>
              <HStack justify="space-between" spacing={2} mb={1.5}>
                <Text fontSize="12px" fontWeight="500" color={colors.text.secondary} noOfLines={1}>
                  {session.progress.label || 'Идёт исследование'}
                </Text>
                {typeof session.progress.percent === 'number' && (
                  <Text
                    fontSize="11px"
                    fontWeight="600"
                    fontFamily="mono"
                    color={colors.blue[300]}
                    flexShrink={0}
                  >
                    {session.progress.percent}%
                  </Text>
                )}
              </HStack>
              {typeof session.progress.percent === 'number' && (
                <Progress value={session.progress.percent} size="xs" colorScheme="blue" borderRadius="full" aria-label={session.progress.label} />
              )}
            </Box>
          )}
          <VStack align="stretch" spacing={0}>
            {visibleTraceEvents.filter((event) => !waitingOffer || !event.offer).map((event, index) => (
              <TraceEventRow
                key={event.id}
                event={event}
                isLast={index === visibleTraceEvents.length - 1 && hiddenTraceEventsCount === 0}
                onRunMode={onRunMode}
                isLoading={isLoading}
              />
            ))}
          </VStack>
          {hiddenTraceEventsCount > 0 && (
            <Text fontSize="11px" color={colors.text.tertiary} pl="22px" pt={1}>
              …ещё {hiddenTraceEventsCount} шаг(ов) скрыто в компактном режиме
            </Text>
          )}
        </Box>
      </TraceDetails>
    </Box>
  );
}

const TraceSessionCard = memo(TraceSessionCardComponent);

export default TraceSessionCard;
