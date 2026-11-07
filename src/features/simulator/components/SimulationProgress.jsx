import React, { useEffect, useState } from 'react';
import { Box, Button, HStack, Progress, Text } from '@chakra-ui/react';
import { SIMULATION_THEME } from '../theme';

export default function SimulationProgress({ stage, phase, progress, reducedMotion, onCancel, canCancel, connectionLost }) {
  const [started] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  const [anchor, setAnchor] = useState(null);
  useEffect(() => {
    const timer = setInterval(() => setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000))), 1000);
    return () => clearInterval(timer);
  }, [started]);
  useEffect(() => {
    if (progress) setAnchor(previous => previous?.phase === progress.phase && previous?.runId === progress.runId && previous?.iteration === progress.iteration
      ? previous : { phase: progress.phase, runId: progress.runId, iteration: progress.iteration, done: progress.done, at: Date.now() });
    else setAnchor(null);
  }, [progress]);
  const elapsedText = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
  const count = progress?.done, total = progress?.total;
  const percent = Number.isFinite(count) && Number.isFinite(total) && total > 0
    ? Math.round(100 * count / total) : null;
  const elapsedSinceAnchor = anchor ? (started + elapsed * 1000 - anchor.at) / 1000 : 0;
  const remaining = anchor && progress?.phase === anchor.phase && progress?.runId === anchor.runId
    && progress?.iteration === anchor.iteration && count - anchor.done >= 2 && elapsedSinceAnchor > 0
    ? Math.ceil(elapsedSinceAnchor / (count - anchor.done) * (total - count)) : null;
  const detail = progress && percent !== null ? `${progress.phase === 'field' ? 'Расчёт поля' : progress.phase === 'geometry' ? 'Проверка геометрии' : progress.phase === 'feedback_cells' ? `Итерация ${progress.iteration} · повтор клеток` : progress.phase === 'network' ? 'Расчёт сети · модельное время' : 'Расчёт клеток'} · ${count} / ${total}${progress.phase === 'network' ? ' мс' : ''} · ${percent}%` : progress?.phase === 'field_verification' ? 'Проверка рассчитанного поля' : progress?.phase === 'feedback_network' ? `Итерация ${progress.iteration} · расчёт сети` : progress?.phase === 'network' ? 'Распространение активности по сети' : `Этап ${phase + 1} из 3`;
  return <Box role="status" aria-live="polite" bg="rgba(6,9,18,.98)" borderTop="1px solid" borderColor={SIMULATION_THEME.panelBorder} px={4} py={3}>
    <HStack justify="space-between" spacing={3}><Text flex={1} fontSize="13px" fontWeight="600">{stage}…</Text><Text fontSize="11px" color="#AAB5CB" whiteSpace="nowrap">{elapsedText}</Text><Button size="xs" variant="outline" onClick={onCancel} isDisabled={!canCancel}>Остановить</Button></HStack>
    <Progress size="xs" isIndeterminate={percent === null && !reducedMotion} value={percent ?? (reducedMotion ? 0 : undefined)} colorScheme="blue" borderRadius="full" mt={2} aria-label={percent === null ? 'Точный процент расчёта недоступен' : 'Прогресс текущего этапа'} />
    <HStack mt={1} spacing={3} justify="space-between">{['Контакты', 'Нейроны', 'Сеть'].map((label, index) => <Text key={label} fontSize="11px" color={index === phase ? '#fff' : '#8792AA'}>{index < phase ? '✓ ' : ''}{label}</Text>)}</HStack>
    <Text fontSize="10px" mt={1} color={connectionLost ? 'orange.200' : '#8792AA'}>{connectionLost ? 'Связь прервана, повторное подключение…' : `${detail}${remaining !== null ? ` · до конца этапа примерно ${remaining} с` : ' · оценка времени до конца этапа уточняется'}`}</Text>
  </Box>;
}
