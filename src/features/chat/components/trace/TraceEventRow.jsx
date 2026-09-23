import React, { memo, useState } from 'react';
import { Box, HStack, Icon, Text } from '@chakra-ui/react';
import { FiAlertCircle, FiCheck, FiChevronDown, FiChevronUp, FiCpu, FiLayers, FiSearch, FiTool, FiZap } from '@shared/icons';
import { colors } from '@theme/tokens';
import { getAgentColor, getAgentLabel, getEventBadgeStyle } from '../../utils/trace';
import ModeOffer from '../ModeOffer';

const norm = (value) => String(value || '').trim().toLowerCase();

// Иконка узла таймлайна по типу события — делает трейс сканируемым с одного взгляда.
function nodeIconFor(kind, title = '') {
  if (kind === 'error') return FiAlertCircle;
  if (kind === 'offer') return FiZap;
  if (kind === 'plan') return FiLayers;
  if (kind === 'done') return FiCheck;
  if (kind === 'thinking') return FiCpu;
  const t = title.toLowerCase();
  if (t.includes('инструмент') || t.includes('tool')) return FiTool;
  if (t.includes('поиск') || t.includes('research') || t.includes('ссыл')) return FiSearch;
  return null;
}

/**
 * Компактная строка таймлайна одного шага трейса: цветная точка (по агенту/статусу),
 * заголовок, опциональный чип агента и время. Деталь показывается только если она
 * добавляет информацию (не дублирует заголовок) — иначе скрывается.
 */
function TraceEventRowComponent({ event, isLast = false, onRunMode, isLoading = false }) {
  // План свёрнут по умолчанию: он длиннее любой другой детали и, развёрнутый всегда,
  // вытеснил бы из панели остальные шаги — а трейс читают, чтобы видеть ход целиком.
  const [planOpen, setPlanOpen] = useState(false);
  const isError = event.kind === 'error';
  const { accent: kindAccent } = getEventBadgeStyle(event.kind);
  const dotColor = isError ? colors.error : getAgentColor(event.agent) || kindAccent;
  const agentLabel = getAgentLabel(event.agent);

  const isThinking = event.kind === 'thinking';
  const isPlan = event.kind === 'plan';
  // 🔴 Предложение дорогого режима живёт ЗДЕСЬ, а не карточкой под готовым ответом:
  // под ответом оно висело вечно, и человек либо жал кнопку задним числом, либо она
  // просто мозолила глаза. В ходе работы решение имеет смысл — там и предлагаем.
  const isOffer = event.kind === 'offer' && event.offer?.mode;
  const title = event.title || '';
  const detail = event.detail || '';
  const NodeIcon = nodeIconFor(event.kind, title);
  const nTitle = norm(title);
  const nDetail = norm(detail);
  // Блок рассуждений показываем всегда; обычные детали — только если они
  // добавляют информацию (не дублируют заголовок).
  const showDetail = isOffer
    ? false
    : isThinking || isPlan
    ? !!nDetail
    : !!nDetail && nDetail !== nTitle && !nTitle.includes(nDetail) && !nDetail.includes(nTitle);

  const _ts = event.timestamp ? new Date(event.timestamp) : null;
  const time = _ts && !Number.isNaN(_ts.getTime())
    ? _ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <HStack align="stretch" spacing={2.5} position="relative" minW={0}>
      {/* Таймлайн: узел (иконка по типу события или точка) + соединительная линия */}
      <Box position="relative" flexShrink={0} w="14px" alignSelf="stretch">
        {NodeIcon ? (
          <Box
            position="absolute"
            left="-1px"
            top="2px"
            boxSize="15px"
            borderRadius="full"
            bg={`${dotColor}1f`}
            border={`1px solid ${dotColor}66`}
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={NodeIcon} boxSize="9px" color={dotColor} />
          </Box>
        ) : (
          <Box
            position="absolute"
            left="3px"
            top="6px"
            w="8px"
            h="8px"
            borderRadius="full"
            bg={dotColor}
            boxShadow={`0 0 0 3px ${dotColor}22`}
          />
        )}
        {!isLast && (
          <Box position="absolute" left="6.5px" top="19px" bottom="-3px" w="1.5px" bg={colors.border.hairline} />
        )}
      </Box>

      <Box flex="1" minW={0} pb={2.5}>
        <HStack
          spacing={2}
          align="flex-start"
          as={isPlan ? 'button' : 'div'}
          w={isPlan ? '100%' : undefined}
          textAlign={isPlan ? 'left' : undefined}
          aria-expanded={isPlan ? planOpen : undefined}
          onClick={isPlan ? () => setPlanOpen((v) => !v) : undefined}
        >
          <Text
            fontSize="13px"
            fontWeight="600"
            color={isError ? colors.error : colors.text.primary}
            noOfLines={2}
            flex="1"
            minW={0}
            lineHeight="1.35"
            overflowWrap="anywhere"
          >
            {title}
            {event._repeatCount > 1 ? ` ×${event._repeatCount}` : ''}
          </Text>
          {isPlan && (
            <Icon as={planOpen ? FiChevronUp : FiChevronDown} boxSize="13px" color={colors.text.tertiary} flexShrink={0} />
          )}
          {agentLabel && (
            <Box
              flexShrink={0}
              fontSize="9.5px"
              fontWeight="700"
              letterSpacing="0.02em"
              textTransform="uppercase"
              px={1.5}
              py="1px"
              borderRadius="full"
              color={dotColor}
              border={`1px solid ${dotColor}66`}
            >
              {agentLabel}
            </Box>
          )}
          {time && (
            <Text fontSize="10px" color={colors.text.tertiary} flexShrink={0} sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {time}
            </Text>
          )}
        </HStack>
        {isOffer && (
          <ModeOffer offer={event.offer} onRun={onRunMode} disabled={isLoading} />
        )}
        {showDetail && isPlan && planOpen && (
          // Текст плана целиком: переносы и нумерация — это его содержание, поэтому
          // pre-wrap и без обрезки строк, в отличие от обычной детали шага.
          <Text
            mt={1}
            fontSize="11.5px"
            color={colors.text.secondary}
            lineHeight="1.55"
            whiteSpace="pre-wrap"
            overflowWrap="anywhere"
            borderLeft={`2px solid ${dotColor}66`}
            pl={2.5}
          >
            {detail}
          </Text>
        )}
        {showDetail && !isPlan && (
          isThinking ? (
            <Text
              mt={1}
              fontSize="11.5px"
              color={colors.text.secondary}
              lineHeight="1.5"
              whiteSpace="pre-wrap"
              overflowWrap="anywhere"
              fontStyle="italic"
              borderLeft="2px solid rgba(167,139,250,0.5)"
              pl={2.5}
            >
              {detail}
            </Text>
          ) : (
            // Плотный многострочный превью: переносы запроса сохраняем (pre-wrap),
            // показываем несколько первых строк/предложений, дальше — многоточие.
            <Text
              mt={0.5}
              fontSize="11.5px"
              color={colors.text.tertiary}
              lineHeight="1.35"
              whiteSpace="pre-wrap"
              overflowWrap="anywhere"
              noOfLines={3}
            >
              {detail}
            </Text>
          )
        )}
      </Box>
    </HStack>
  );
}

const TraceEventRow = memo(TraceEventRowComponent);

export default TraceEventRow;
