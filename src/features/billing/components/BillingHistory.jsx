import { Box, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import {
  FiFileText,
  FiPlusCircle,
  FiRotateCcw,
  FiSliders,
  FiStar,
  FiZap,
} from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, CARD_HOVER_SOFT, CARD_TRANSITION } from '@theme/glass';
import { CHAT_THEME } from '../../chat/constants/theme';
import { eventLabel, formatCredits, formatRub } from '../lib/credits';
import { MICRO_LABEL_SX } from '@theme/styles';
import ModelChip from './ModelChip';

// Икона/цвет/знак/природа суммы по типу события.
const TYPE_META = {
  usage: { icon: FiZap, color: colors.fg[3], sign: '−', kind: 'credits' },
  topup: { icon: FiPlusCircle, color: colors.success, sign: '+', kind: 'amount' },
  subscription_grant: { icon: FiStar, color: colors.blue[300], sign: '+', kind: 'amount' },
  refund: { icon: FiRotateCcw, color: colors.cyan[300], sign: '+', kind: 'credits' },
  adjustment: { icon: FiSliders, color: colors.warning, sign: '', kind: 'credits' },
};
const FALLBACK_META = { icon: FiFileText, color: colors.fg[4], sign: '', kind: 'credits' };

// Ключ группы — ЛОКАЛЬНАЯ дата: подпись группы и время строк тоже локальные.
// По UTC (toISOString) события у границы часового пояса попадали в разные группы,
// а подписывались одной датой — и один день рисовался двумя заголовками.
function dayKey(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso || '');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}
function dayLabel(iso) {
  try {
    return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
  } catch {
    return iso || '';
  }
}
function timeLabel(iso) {
  try {
    return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function groupByDay(events) {
  const groups = [];
  const index = new Map();
  for (const event of events) {
    const key = dayKey(event.created_at);
    if (!index.has(key)) {
      const group = { key, label: dayLabel(event.created_at), items: [] };
      index.set(key, group);
      groups.push(group);
    }
    index.get(key).items.push(event);
  }
  return groups;
}

function EmptyState({ message = 'Пока нет операций' }) {
  return (
    <VStack spacing={2.5} py={10} px={4} textAlign="center">
      <Box
        boxSize="44px"
        borderRadius={borderRadius.md}
        bg={CHAT_THEME.accentSoft}
        border={`1px solid ${colors.accent.subtleBorder}`}
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Box as={FiFileText} color={colors.blue[300]} fontSize="20px" />
      </Box>
      <Text fontSize="13px" color={CHAT_THEME.textSecondary} fontWeight="500">
        {message}
      </Text>
    </VStack>
  );
}

function EventRow({ event }) {
  const meta = TYPE_META[event.event_type] || FALLBACK_META;
  const model = event.model || event.metadata?.model;
  const amountText =
    meta.kind === 'amount' && event.amount
      ? `${meta.sign}${formatRub(event.amount)}`
      : `${meta.sign}${formatCredits(event.credits)} кр`;
  return (
    <HStack
      justify="space-between"
      align="center"
      spacing={3}
      p={3}
      {...GLASS_SURFACE}
      borderRadius={borderRadius.md}
      transition={CARD_TRANSITION}
      _hover={CARD_HOVER_SOFT}
    >
      <HStack spacing={3} minW={0}>
        <Box
          flexShrink={0}
          boxSize="30px"
          borderRadius={borderRadius.sm}
          bg={CHAT_THEME.panelHover}
          border={`1px solid ${colors.border.subtle}`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={meta.icon} boxSize={3.5} color={meta.color} />
        </Box>
        <VStack align="start" spacing={0.5} minW={0}>
          <Text fontSize="13px" fontWeight="600" color={CHAT_THEME.textPrimary} noOfLines={1}>
            {eventLabel(event.event_type)}
          </Text>
          <HStack spacing={2} minW={0}>
            <Text fontSize="11px" color={CHAT_THEME.textTertiary} flexShrink={0}>
              {timeLabel(event.created_at)}
            </Text>
            {event.event_type === 'usage' && model && <ModelChip model={model} />}
          </HStack>
        </VStack>
      </HStack>
      <Text fontSize="13px" fontWeight="600" color={meta.color} flexShrink={0}>
        {amountText}
      </Text>
    </HStack>
  );
}

export default function BillingHistory({ events = [], emptyMessage }) {
  if (!events.length) return <EmptyState message={emptyMessage} />;
  const groups = groupByDay(events);
  return (
    <VStack align="stretch" spacing={4}>
      {groups.map((group) => (
        <Box key={group.key}>
          <Text {...MICRO_LABEL_SX} mb={2} px={1}>
            {group.label}
          </Text>
          <VStack align="stretch" spacing={2}>
            {group.items.map((event, index) => (
              <EventRow key={`${event.created_at}-${index}`} event={event} />
            ))}
          </VStack>
        </Box>
      ))}
    </VStack>
  );
}
