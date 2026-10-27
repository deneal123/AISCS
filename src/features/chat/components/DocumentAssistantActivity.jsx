import React, { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Box, Button, HStack, Text } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';

const TracePanel = lazy(() => import('./trace/TracePanel'));

/** Compact PDF variant of Chat's trace, with the same confirmation and Stop owners. */
export default function DocumentAssistantActivity({ state, messages, onStop, onOpenChat, onDetailsChange, variant = 'document', notice = '' }) {
  const { session, anchor, running, tracing, expired } = state;
  const [details, setDetails] = useState(false);
  const regionRef = useRef(null);
  useEffect(() => {
    if (tracing && (document.activeElement === document.body
      || document.activeElement?.closest('[data-composer-container]'))) {
      regionRef.current?.focus({ preventScroll: true });
    }
  }, [tracing]);
  useLayoutEffect(() => { setDetails(false); }, [session?.id]);
  useLayoutEffect(() => {
    onDetailsChange?.(details);
    return () => onDetailsChange?.(false);
  }, [details, onDetailsChange]);
  const showTrace = Boolean(session && (tracing || details));
  const summary = notice || (expired ? 'Срок подтверждения истёк. Платный запуск не начат.'
    : state.taskResult ? `${state.taskResult.title}. ${state.taskResult.detail}`
    : session?.status === 'error' ? 'Запрос не завершён. Подробности — в этапах.'
      : session?.status === 'cancelled' ? 'Запрос остановлен.'
        : session?.status === 'done' ? variant === 'ide' ? 'Запрос завершён.' : 'Запрос завершён. Ответ доступен в Чате.'
          : 'Результат запроса можно уточнить в Чате.');
  if (!tracing && !session && !messages.error && !notice && !state.taskResult) return null;
  return <Box ref={regionRef} role="region" aria-label={variant === 'ide' ? 'Выполнение запроса IDE' : 'Выполнение запроса документа'} tabIndex={-1}
    data-testid="document-assistant-activity" minH={0} display="flex" flexDirection="column"
    overflow="hidden"
    flexShrink={showTrace ? 1 : 0}
    flex={variant === 'ide' && tracing ? '1' : undefined} h={variant === 'ide' && tracing ? 'full' : showTrace ? 'min(360px, calc(var(--app-visual-height, 100dvh) * 0.42))' : undefined}
    _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
    <HStack px={4} py={2} spacing={2} flexWrap="wrap" flexShrink={0}>
      <Text flex="1" minW="120px" fontSize="12px" color={colors.fg[3]} role="status">
        {tracing ? state.waiting ? 'Нужно ваше решение' : 'Выполняю запрос…' : summary}
      </Text>
      {running && <Button size="workbench" variant="workbenchSecondary"
        aria-label="Остановить генерацию" onClick={onStop}>Остановить</Button>}
      {!tracing && session && <Button size="workbench" variant="ghost" aria-expanded={details}
        onClick={() => setDetails(!details)}>{details ? 'Скрыть этапы' : 'Этапы'}</Button>}
      {onOpenChat && <Button size="workbench" variant="ghost" onClick={onOpenChat}>Открыть в Чате</Button>}
    </HStack>
    {messages.error && <Text role="alert" px={4} pb={2} fontSize="12px" color={colors.warning}>{messages.error}</Text>}
    {showTrace ? <Box px={3} pb={3} flex="1" minH={0} minW={0} display="flex" overflow="hidden"
      sx={{ animation: 'pdf-trace-in 160ms ease-out',
        '@keyframes pdf-trace-in': { from: { opacity: 0, transform: 'translateY(6px)' }, to: { opacity: 1, transform: 'none' } },
        '@media (prefers-reduced-motion: reduce)': { animation: 'none' } }}>
      <Suspense fallback={<AppLoading label="Загружаю этапы…" />}>
        <TracePanel layout="workbench" sessions={[session]} expandedMap={tracing ? messages.tracePanelsExpanded || {} : { [session.id]: true }}
          isCompactTrace={messages.isCompactTrace} onToggleExpanded={tracing ? messages.onTraceToggle || (() => {}) : (_id, expanded) => setDetails(expanded)}
          onRunMode={messages.onRunMode ? (offer) => messages.onRunMode(offer, anchor?.content, anchor?.id, session.id) : undefined}
          isLoading={running} stopHint="Можно остановить запрос кнопкой «Остановить» над этапами." />
      </Suspense>
    </Box> : tracing && <Text px={4} pb={3} role="status" fontSize="12px" color={colors.fg[3]}>
      Ожидаю этапы обработки. Неподтверждённый прогресс не отображается.
    </Text>}
  </Box>;
}
