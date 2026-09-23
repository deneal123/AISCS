import { useEffect, useRef, useState } from 'react';
import { Box, Text, Tooltip, VStack } from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';

const GOLD = colors.spectral.amber; // #FFC56E — единственный «золотой» в системе
const GOLD_PEAK = '#ffe7b0';

const SECTION_LABELS = {
  // Постоянная часть промпта: инструкции агента, секция личности, схемы инструментов.
  // ⚠️ Показываем ПЕРВОЙ строкой смысла ради: на коротком диалоге это и есть весь
  // занятый контекст (замер: 1.1k токенов из 1.1k), и без неё кольцо показывало ноль.
  system: 'инструкции агента',
  input: 'запрос',
  facts: 'факты',
  memory: 'память',
  files: 'вложения',
  knowledge: 'база знаний',
  plan: 'план',
  summary: 'резюме',
  history: 'история',
};

const fmt = (n) => {
  const v = Number(n) || 0;
  if (v >= 1000) return `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k`;
  return String(v);
};

/**
 * Кольцо-индикатор заполнения контекстного окна (как в Claude Code), золотое —
 * фирменная амбер-палитра. Показывает, сколько из бюджета модели ЗАЙМЁТ следующий
 * запрос (бэкенд считает это при сборке контекста), а не сколько токенов потрачено
 * за тред. Поэтому после сжатия кольцо реально падает — и мы подсвечиваем это
 * вспышкой, иначе пользователь не замечает, что сжатие сработало.
 *
 * Клик → компактизация. Красного в системе нет: тревога на высоком заполнении
 * передаётся яркостью свечения, а не сменой оттенка.
 */
export default function ContextGauge({
  pct = 0,
  tokens = 0,
  windowTokens = 0,
  modelWindow = 0,
  bySection = {},
  threshold = 85,
  onCompact,
  busy = false,
}) {
  const size = 30;
  const stroke = 3;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
  const dash = (clamped / 100) * circ;
  const high = clamped >= threshold;

  // Заполнение упало (сжатие сработало) → короткая вспышка «контекст освободился».
  const prevPct = useRef(clamped);
  const [relief, setRelief] = useState(false);
  useEffect(() => {
    if (prevPct.current - clamped > 8) {
      setRelief(true);
      const t = setTimeout(() => setRelief(false), 900);
      return () => clearTimeout(t);
    }
    prevPct.current = clamped;
    return undefined;
  }, [clamped]);
  useEffect(() => {
    if (!relief) prevPct.current = clamped;
  }, [relief, clamped]);

  const parts = Object.entries(bySection)
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => b[1] - a[1]);

  const ringAnimation = relief
    ? 'ctx-gauge-relief 900ms cubic-bezier(0.16, 1, 0.3, 1)'
    : high
      ? 'ctx-gauge-alert 2.4s ease-in-out infinite'
      : 'none';

  const tip = (
    <VStack align="stretch" spacing={1}>
      <Text fontWeight="700">
        {busy ? 'Сжатие контекста…' : `Контекст ${Math.round(clamped)}% · ${fmt(tokens)} / ${fmt(windowTokens)} токенов`}
      </Text>
      {!busy && parts.length > 0 && (
        <Text color={CHAT_THEME.textSecondary}>
          {parts.map(([k, v]) => `${SECTION_LABELS[k] || k} ${fmt(v)}`).join(' · ')}
        </Text>
      )}
      {!busy && modelWindow > 0 && (
        <Text color={CHAT_THEME.textTertiary}>Окно модели: {fmt(modelWindow)}</Text>
      )}
      {!busy && <Text color={CHAT_THEME.textTertiary}>Клик — сжать диалог в долговременную память</Text>}
    </VStack>
  );

  return (
    <Tooltip
      label={tip}
      placement="top"
      hasArrow
      openDelay={200}
      bg={CHAT_THEME.sidebarBg}
      color={CHAT_THEME.textPrimary}
      border={`1px solid ${CHAT_THEME.panelBorder}`}
      borderRadius="8px"
      fontSize="12px"
      px={3}
      py={2}
      maxW="280px"
    >
      <Box
        as="button"
        type="button"
        onClick={onCompact}
        disabled={busy}
        aria-label={`Контекст заполнен на ${Math.round(clamped)}%. Сжать в долговременную память`}
        position="relative"
        w={`${size}px`}
        h={`${size}px`}
        flexShrink={0}
        borderRadius="full"
        transition="transform 160ms cubic-bezier(0.16, 1, 0.3, 1)"
        _hover={{ transform: busy ? 'none' : 'scale(1.1)' }}
        _active={{ transform: busy ? 'none' : 'scale(0.88)' }}
        _focusVisible={{ outline: `2px solid ${GOLD}`, outlineOffset: '2px' }}
        sx={
          busy
            ? { animation: 'ctx-gauge-busy 1.1s ease-in-out infinite' }
            : undefined
        }
        className={busy ? 'ctx-gauge-busy' : undefined}
      >
        <Box as="svg" width={size} height={size} sx={{ transform: 'rotate(-90deg)', display: 'block' }}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={CHAT_THEME.panelBorder} strokeWidth={stroke} />
          <Box
            as="circle"
            className="ctx-gauge-ring"
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={high ? GOLD_PEAK : GOLD}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circ}`}
            sx={{
              transformOrigin: 'center',
              filter: `drop-shadow(0 0 3px rgba(255,197,110,0.55))`,
              animation: ringAnimation,
              // Заполнение перетекает пружиной, а не линейно: падение после сжатия
              // читается как жест, а не как скачок значения.
              transition: 'stroke-dasharray 620ms cubic-bezier(0.16, 1, 0.3, 1), stroke 300ms ease',
            }}
          />
        </Box>
        <Text
          position="absolute"
          top="50%"
          left="50%"
          transform="translate(-50%, -50%)"
          fontSize="8.5px"
          fontWeight="700"
          fontFamily="mono"
          color={high ? GOLD_PEAK : CHAT_THEME.textSecondary}
          lineHeight="1"
          pointerEvents="none"
          transition="color 300ms ease"
        >
          {Math.round(clamped)}
        </Text>
      </Box>
    </Tooltip>
  );
}
