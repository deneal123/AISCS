import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, HStack, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import PopulationTargetReplay from '../recording/PopulationTargetReplay';

export default function NeuronConnections({ runId, nodeId, fragmentRunId, onShowTarget, onFocusProbe, onClose, onSelectNode, positionDescription, onFocusNode, canFocusNode, onPage, morphology, neighborMorphology, synapses }) {
  const onPageRef = useRef(onPage);
  onPageRef.current = onPage;
  const [offset, setOffset] = useState(0);
  const [direction, setDirection] = useState('outgoing');
  const [state, setState] = useState({ loading: true, page: null, error: false });
  const [attempt, setAttempt] = useState(0);
  const [candidateAttempt, setCandidateAttempt] = useState(0);
  const [candidates, setCandidates] = useState(null);
  useEffect(() => {
    if (!fragmentRunId || !candidateAttempt) return undefined;
    const controller = new AbortController();
    setCandidates({ loading: true });
    simulationApi.populationTargetCandidates(fragmentRunId, nodeId, controller.signal).then(result => {
      if (!controller.signal.aborted) setCandidates({ result });
    }).catch(() => {
      if (!controller.signal.aborted) setCandidates({ error: true });
    });
    return () => controller.abort();
  }, [fragmentRunId, nodeId, candidateAttempt]);
  useEffect(() => { setOffset(0); }, [runId, nodeId]);
  useEffect(() => {
    const controller = new AbortController();
    onPageRef.current?.(null);
    setState({ loading: true, page: null, error: false });
    simulationApi[direction](runId, nodeId, offset, controller.signal).then(page => {
      if (!controller.signal.aborted) {
        setState({ loading: false, page, error: false });
        onPageRef.current?.({ nodeId, direction, offset, items: page.items });
      }
    }).catch(() => {
      if (!controller.signal.aborted) setState({ loading: false, page: null, error: true });
    });
    return () => controller.abort();
  }, [runId, nodeId, offset, attempt, direction]);
  const page = state.page;
  return <Box as="section" aria-label={direction === 'outgoing' ? 'Исходящие связи нейрона' : 'Входящие связи нейрона'} position="absolute" right={3} top="112px" w="300px"
    maxH="55%" overflowY="auto" bg="rgba(6,9,20,.97)" border="1px solid #31405d" borderRadius="6px" p={3} fontSize="12px">
    <HStack mb={2}><Text fontWeight="bold" flex={1}>Нейрон {nodeId}</Text><Button size="xs" variant="ghost" onClick={onClose}>Закрыть</Button></HStack>
    {positionDescription && <Text color="gray.400" mb={2}>{positionDescription}</Text>}
    {morphology?.loading && <Text role="status" color="gray.400">Загрузка исходного отростка…</Text>}
    {morphology?.data && <Text color="gray.400" mb={2}>Исходная SWC-морфология · {morphology.data.vertices.toLocaleString('ru-RU')} вершин</Text>}
    {morphology?.error && <Box mb={2}><Text role="status" color="orange.200">{morphology.error}</Text><Button size="xs" variant="ghost" onClick={morphology.retry}>Повторить загрузку морфологии</Button></Box>}
    {neighborMorphology?.total > 0 && <Text color="gray.400" mb={2}>
      {neighborMorphology.data ? `Морфология соседних нейронов: ${neighborMorphology.loaded} из ${neighborMorphology.total}${neighborMorphology.loading ? ' · загрузка' : ''}` : 'Загрузка соседних нейронов…'}
    </Text>}
    {neighborMorphology?.unavailable > 0 && <Button size="xs" variant="ghost" onClick={neighborMorphology.retry}>Повторить загрузку соседних нейронов</Button>}
    {neighborMorphology?.omitted > 0 && <Text color="gray.400" mb={2}>Часть отростков не показана из-за объёма сцены.</Text>}
    {page && <Text color="gray.400" mb={2}>Показаны реконструкции выбранного и соседних нейронов. Связи перечислены ниже.</Text>}
    {synapses?.loading && <Text role="status" color="gray.400" mb={2}>Загрузка координат синапсов…</Text>}
    {synapses?.data && <Text color="gray.400" mb={2}>Прогнозируемые синапсы: {synapses.data.returned} из {synapses.data.total}{synapses.data.truncated ? ' · показана часть' : ''}. Цвет отражает спайк пресинаптического нейрона.</Text>}
    {synapses?.error && <Box mb={2}><Text role="status" color="orange.200">Координаты синапсов недоступны.</Text><Button size="xs" variant="ghost" onClick={synapses.retry}>Повторить</Button></Box>}
    <Button size="xs" variant="outline" mb={2} isDisabled={!canFocusNode} onClick={onFocusNode}>Приблизить нейрон</Button>
    {fragmentRunId && <Box mb={3}>
      <Button size="xs" variant="outline" isLoading={Boolean(candidates?.loading)} onClick={() => setCandidateAttempt(value => value + 1)}>
        Проверить входящие события
      </Button>
      {candidates?.error && <Text role="alert" color="orange.200" mt={2}>Не удалось проверить события. Повторите попытку.</Text>}
      {candidates?.result && <Box mt={2}>
        <Text>Источники событий: {candidates.result.candidates.length} · шаг графа 1 мс</Text>
        {candidates.result.candidates.map(item => <Text key={item.source_id} color="gray.300">
          Нейрон {item.source_id}: {item.events}, первое — {item.first_tick_ms} мс
        </Text>)}
        <Text color="gray.400" mt={1}>События графовой модели; геометрия и физиология связей требуют проверки.</Text>
        {candidates.result.candidates.length > 0 && <PopulationTargetReplay key={`${fragmentRunId}:${nodeId}`}
          runId={fragmentRunId} nodeId={nodeId} candidates={candidates.result.candidates} onShowOnTimeline={onShowTarget} onFocusProbe={onFocusProbe} morphologyHash={morphology?.data?.sha256} />}
      </Box>}
    </Box>}
    <HStack mb={2}>{[['outgoing', 'Исходящие'], ['incoming', 'Входящие']].map(([key, label]) =>
      <Button key={key} size="xs" variant={direction === key ? 'solid' : 'outline'} aria-pressed={direction === key}
        onClick={() => { setOffset(0); setDirection(key); }}>{label}</Button>)}</HStack>
    {state.loading && <Text role="status">Загрузка связей…</Text>}
    {state.error && <><Text role="alert">Не удалось загрузить связи.</Text><Button size="xs" mt={2} onClick={() => setAttempt(value => value + 1)}>Повторить</Button></>}
    {page && <><Text>{direction === 'outgoing' ? 'Исходящих' : 'Входящих'} связей: {page.total}</Text>
      <Text color="gray.400" mb={2}>Число синапсов; знак LIF основан на предсказании медиатора без учёта рецепторов.</Text>
      {page.items.map(item => {
        const neighbor = item.target_id || item.source_id;
        return <HStack key={neighbor} spacing={1}>
          <Button size="xs" variant="link" color="blue.200" aria-label={`Открыть нейрон ${neighbor}`} onClick={() => onSelectNode?.(neighbor)}>
            {direction === 'outgoing' ? '→' : '←'} {neighbor}
          </Button>
          <Text>· {item.synapse_count} · {item.model_sign > 0 ? '+' : item.model_sign < 0 ? '−' : '?'}</Text>
        </HStack>;
      })}
      {!page.items.length && <Text>На этой странице связей нет.</Text>}
      <HStack mt={2}><Button size="xs" isDisabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Назад</Button>
        <Button size="xs" isDisabled={page.next_offset === null} onClick={() => setOffset(page.next_offset)}>Далее</Button></HStack>
    </>}
  </Box>;
}
