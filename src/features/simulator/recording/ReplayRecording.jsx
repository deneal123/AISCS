import React, { useEffect, useState } from 'react';
import { Box, Button, HStack, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import SignalPlot from './SignalPlot';
import { SIMULATION_THEME } from '../theme';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);

// This is a separate one-cell calculation associated with the source network run.
export default function ReplayRecording({ sourceId, timeMs, onTime }) {
  const [state, setState] = useState({ loading: true, items: [], selected: null, error: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    setState({ loading: true, items: [], selected: null, error: false });
    async function load() {
      try {
        const result = await simulationApi.replays(sourceId, controller.signal);
        const items = result.items || [];
        const latest = items.find(item => item.state === 'completed');
        const selected = latest ? await simulationApi.get(latest.id, controller.signal) : null;
        if (controller.signal.aborted) return;
        setState({ loading: false, items, selected, error: false });
        if (items.some(item => active.has(item.state))) timer = setTimeout(load, 10000);
      } catch {
        if (!controller.signal.aborted) setState({ loading: false, items: [], selected: null, error: true });
      }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [sourceId, attempt]);
  if (state.loading) return null;
  if (state.error) return <HStack fontSize="12px" role="status"><Text>Дополнительная запись недоступна.</Text><Button size="xs" variant="ghost" onClick={() => setAttempt(value => value + 1)}>Повторить</Button></HStack>;
  if (!state.items.length) return null;
  const preview = state.selected?.result?.preview;
  const contacts = state.selected?.configuration?.simulation;
  const contactText = values => Array.isArray(values) && values.length === 3 && values.every(Number.isFinite)
    ? values.map(String).join(', ') : null;
  const e1 = contactText(contacts?.electrode_um), ref = contactText(contacts?.reference_um);
  const latest = state.items[0];
  const priorShown = preview && latest?.id !== state.selected.id;
  return <Box as="section" aria-label="Дополнительная запись нейрона" borderTop="1px solid" borderColor={SIMULATION_THEME.panelBorder} pt={4}>
    <Text fontSize="14px" fontWeight="600">Дополнительная запись нейрона{preview ? ` ${preview.body_id}` : ''}</Text>
    <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={1}>Одностороннее воспроизведение событий сети на морфологии одной клетки. Параметры не откалиброваны; это не запись всей ЦНС.</Text>
    {state.items.some(item => active.has(item.state)) && <Text fontSize="12px" mt={1}>Расчёт выполняется…</Text>}
    {priorShown && <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={1}>Показана предыдущая завершённая запись{latest?.state === 'failed' ? '; последний расчёт завершился ошибкой' : latest?.state === 'cancelled' ? '; последний расчёт остановлен' : ''}.</Text>}
    {preview && <><Text fontSize="12px" mt={3}>Нейронная составляющая E1 − REF, мкВ</Text>
      <SignalPlot preview={preview} timeMs={Math.min(timeMs, preview.time_ms.at(-1))} onTime={onTime} />
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Артефакт стимуляции в этой трассе не показан. Контакты этой записи заданы отдельно от электродов на сцене.</Text>
      {e1 && ref && <Box as="details" mt={2} fontSize="12px"><summary>Координаты контактов записи</summary>
        <Text color={SIMULATION_THEME.textSecondary} mt={1}>Исходная система MaleCNS, мкм · E1: ({e1}) · REF: ({ref})</Text></Box>}</>}
    {!preview && !state.items.some(item => active.has(item.state)) && <Text fontSize="12px" mt={2}>{latest?.state === 'failed' ? 'Последний расчёт завершился ошибкой.' : latest?.state === 'cancelled' ? 'Последний расчёт остановлен.' : 'Завершённых записей нет.'}</Text>}
  </Box>;
}
