import { useMemo } from 'react';
import { Box, HStack, Text, VStack } from '@chakra-ui/react';
import { FiBarChart2 } from '@shared/icons';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';
import { CHAT_THEME } from '../../../chat/constants/theme';
import { formatCredits, formatTokens, modelLabel, pct, rubFromCredits } from '../../lib/credits';

const PROMPT_COLOR = colors.iris[500];
const COMPLETION_COLOR = colors.cyan[500];

function TooltipRow({ label, value, color }) {
  return (
    <HStack justify="space-between" spacing={4}>
      <HStack spacing={1.5}>
        {color && <Box boxSize="8px" borderRadius="2px" bg={color} />}
        <Text fontSize="12px" color={CHAT_THEME.textSecondary}>{label}</Text>
      </HStack>
      <Text fontSize="12px" fontWeight="600" color={CHAT_THEME.textPrimary}>{value}</Text>
    </HStack>
  );
}

// Богатый инлайн-тултип: модель, prompt/completion токены, всего токенов,
// кредиты, ₽, доля от общего.
function makeTooltip({ rate, totalTokens, totalCredits, hasSplit }) {
  return function SplitTooltip({ active, payload }) {
    if (!active || !payload || !payload.length) return null;
    const row = payload[0].payload || {};
    const rub = rubFromCredits(row.credits, rate);
    const share = hasSplit ? pct(row.tokens, totalTokens) : pct(row.credits, totalCredits);
    return (
      <Box
        px={3}
        py={2}
        minW="196px"
        bg={colors.ink[900]}
        border={`1px solid ${colors.glass.border}`}
        borderRadius={borderRadius.sm}
        boxShadow={colors.glass.highlight}
      >
        <Text fontSize="12px" fontWeight="700" color={CHAT_THEME.textPrimary} mb={1.5} noOfLines={1}>
          {modelLabel(row.name)}
        </Text>
        <VStack align="stretch" spacing={1}>
          {hasSplit && (
            <>
              <TooltipRow label="Prompt" value={formatTokens(row.prompt_tokens)} color={PROMPT_COLOR} />
              <TooltipRow label="Completion" value={formatTokens(row.completion_tokens)} color={COMPLETION_COLOR} />
              <TooltipRow label="Всего токенов" value={formatTokens(row.tokens)} />
            </>
          )}
          <TooltipRow label="Кредиты" value={formatCredits(row.credits)} />
          {rub && (
            <HStack justify="space-between" spacing={4}>
              <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Стоимость</Text>
              <Text fontSize="12px" fontWeight="600" color={colors.accent.subtleText}>{rub}</Text>
            </HStack>
          )}
          <TooltipRow label="Доля" value={`${share}%`} />
        </VStack>
      </Box>
    );
  };
}

function LegendSwatch({ color, label }) {
  return (
    <HStack spacing={1.5}>
      <Box boxSize="9px" borderRadius="2px" bg={color} />
      <Text fontSize="11px" color={CHAT_THEME.textTertiary}>{label}</Text>
    </HStack>
  );
}

function EmptyState({ title }) {
  return (
    <Box>
      {title && (
        <Text fontSize="12px" color={CHAT_THEME.textSecondary} mb={2}>{title}</Text>
      )}
      <VStack {...GLASS_SURFACE} borderRadius={borderRadius.md} spacing={2.5} py={10} px={4} textAlign="center">
        <Box
          boxSize="40px"
          borderRadius={borderRadius.md}
          bg={CHAT_THEME.accentSoft}
          border={`1px solid ${colors.accent.subtleBorder}`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Box as={FiBarChart2} color={colors.blue[300]} fontSize="18px" />
        </Box>
        <Text fontSize="12.5px" color={CHAT_THEME.textSecondary} fontWeight="500">
          Пока нет разбивки по моделям
        </Text>
      </VStack>
    </Box>
  );
}

/**
 * Центральный график аналитики: по каждой модели — стек prompt (iris) vs
 * completion (cyan) токенов. Если бэкенд ещё не отдаёт токен-сплит — деградирует
 * к барам кредитов. Красный не используется (он только для ошибок).
 */
export default function TokenSplitChart({ data = [], rate, title = 'По моделям' }) {
  // Хуки — до раннего return (см. комментарий в BreakdownBars).
  const hasSplit = useMemo(
    () => data.some((d) => (d.prompt_tokens || 0) + (d.completion_tokens || 0) > 0),
    [data],
  );
  const totalTokens = useMemo(
    () => data.reduce((sum, d) => sum + (Number(d.tokens) || 0), 0),
    [data],
  );
  const totalCredits = useMemo(
    () => data.reduce((sum, d) => sum + (Number(d.credits) || 0), 0),
    [data],
  );
  const Tip = useMemo(
    () => makeTooltip({ rate, totalTokens, totalCredits, hasSplit }),
    [rate, totalTokens, totalCredits, hasSplit],
  );

  if (!data.length) return <EmptyState title={title} />;

  const height = Math.max(170, data.length * 40 + 24);

  return (
    <Box>
      <HStack justify="space-between" align="center" mb={2} flexWrap="wrap" gap={2}>
        <Text fontSize="12px" color={CHAT_THEME.textSecondary}>{title}</Text>
        {hasSplit && (
          <HStack spacing={3}>
            <LegendSwatch color={PROMPT_COLOR} label="Prompt" />
            <LegendSwatch color={COMPLETION_COLOR} label="Completion" />
          </HStack>
        )}
      </HStack>
      <Box h={`${height}px`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 4, bottom: 0 }} barCategoryGap="28%">
            <XAxis type="number" tick={{ fontSize: 10, fill: colors.fg[4] }} tickFormatter={formatTokens} />
            <YAxis
              type="category"
              dataKey="name"
              width={132}
              interval={0}
              tickFormatter={modelLabel}
              tick={{ fontSize: 10.5, fill: colors.fg[3] }}
            />
            <Tooltip content={<Tip />} cursor={{ fill: colors.border.faint }} />
            {/* Массив, а не Fragment: recharts findAllByType не заходит внутрь фрагментов. */}
            {hasSplit
              ? [
                  <Bar key="prompt" dataKey="prompt_tokens" stackId="t" fill={PROMPT_COLOR} radius={[4, 0, 0, 4]} />,
                  <Bar key="completion" dataKey="completion_tokens" stackId="t" fill={COMPLETION_COLOR} radius={[0, 4, 4, 0]} />,
                ]
              : <Bar dataKey="credits" fill={colors.blue[500]} radius={[0, 4, 4, 0]} />}
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}
