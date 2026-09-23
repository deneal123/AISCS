import React, { memo, useMemo } from 'react';
import { Box, Collapse, HStack, Icon, Spinner, Text, VStack } from '@chakra-ui/react';
import { FiAlertCircle, FiCheckCircle, FiChevronDown } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import TraceEventRow from './TraceEventRow';
import { getSessionStatus } from '../../utils/trace';

function TraceSessionCardComponent({ session, isCompactTrace, isExpanded, onToggleExpanded, onRunMode, isLoading }) {
  const stepCount = (session.events || []).length;
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
  // ⚠️ «Ход работы», а не «Ход рассуждения». Панель показывает ШАГИ ОБРАБОТКИ
  // (маршрутизация, сборка контекста, вызовы инструментов), а рассуждения модели — лишь
  // один из шагов и бывают не у всякой модели. Прежний заголовок обещал именно их:
  // человек видел «Ход рассуждения · 7 шагов» на модели без reasoning и справедливо
  // спрашивал, где размышления.
  const headerTitle = isRunning
    ? 'Готовлю ответ…'
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
      maxW="860px"
      borderRadius={borderRadius.md}
      border={`1px solid ${borderColor}`}
      bg={colors.surface.tint2}
      overflow="hidden"
      boxShadow={isRunning ? `0 10px 32px ${colors.accent.subtle}` : 'none'}
    >
      <HStack
        as="button"
        type="button"
        onClick={() => onToggleExpanded(!isExpanded)}
        w="100%"
        px={{ base: 3, md: 3.5 }}
        py={2.75}
        spacing={2}
        textAlign="left"
        transition="background 0.15s"
        _hover={{ bg: colors.surface.tint2 }}
      >
        {isRunning ? (
          <Spinner size="xs" color={colors.iris[500]} flexShrink={0} />
        ) : (
          <Icon
            as={isError ? FiAlertCircle : FiCheckCircle}
            color={isError ? colors.error : colors.success}
            boxSize={4}
            flexShrink={0}
          />
        )}
        <Text fontSize="13px" fontWeight="650" color={colors.text.primary} minW={0} noOfLines={1}>
          {headerTitle}
        </Text>
        <Text fontSize="11px" color={colors.text.tertiary} flexShrink={0} whiteSpace="nowrap">
          {stepCount} {stepCount === 1 ? 'шаг' : 'шагов'}
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

      <Collapse in={isExpanded} animateOpacity>
        <Box px={{ base: 3, md: 4 }} pb={3.5} pt={2}>
          {isRunning && session.progress && (
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
              <Box h="5px" borderRadius="full" bg={colors.border.subtle} overflow="hidden">
                <Box
                  h="100%"
                  borderRadius="full"
                  bg={colors.blue[500]}
                  boxShadow={`0 0 8px ${colors.accent.subtle}`}
                  transition="width 0.4s cubic-bezier(0.16,1,0.3,1)"
                  width={
                    typeof session.progress.percent === 'number'
                      ? `${session.progress.percent}%`
                      : '25%'
                  }
                />
              </Box>
            </Box>
          )}
          <VStack align="stretch" spacing={0}>
            {visibleTraceEvents.map((event, index) => (
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
      </Collapse>
    </Box>
  );
}

const TraceSessionCard = memo(TraceSessionCardComponent);

export default TraceSessionCard;
