import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, ButtonGroup, HStack, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import { SIMULATION_THEME } from '../theme';

const names = ['STIM+', 'STIM−', 'E1', 'REF'];

export default function FieldContactScreen({ sceneRunId, simulation, disabled, onSelectContact }) {
  const [state, setState] = useState({ loading: false, result: null, error: '' });
  const [alternatives, setAlternatives] = useState({ loading: false, positions: null, error: '' });
  const [contact, setContact] = useState('0');
  const [searchDistance, setSearchDistance] = useState(25);
  const pending = useRef(null);
  const pendingAlternatives = useRef(null);
  const points = [simulation.source_um, simulation.return_um, simulation.electrode_um, simulation.reference_um];
  const signature = JSON.stringify([sceneRunId, points, simulation.clearance_um]);
  const current = useRef(signature);
  current.current = signature;
  useEffect(() => {
    pending.current?.abort(); pending.current = null;
    pendingAlternatives.current?.abort(); pendingAlternatives.current = null;
    setState({ loading: false, result: null, error: '' });
    setAlternatives({ loading: false, positions: null, error: '' });
    setSearchDistance(25);
    return () => { pending.current?.abort(); pending.current = null; pendingAlternatives.current?.abort(); pendingAlternatives.current = null; };
  }, [signature]);
  const clearance = Number(simulation.clearance_um);
  const valid = Boolean(sceneRunId && String(simulation.clearance_um).trim() !== ''
    && Number.isFinite(clearance) && clearance > 0
    && points.every(point => Array.isArray(point) && point.length === 3
      && point.every(value => String(value).trim() !== '' && Number.isFinite(Number(value)))));
  const screen = async () => {
    if (!valid || disabled || state.loading) return;
    const controller = new AbortController(); pending.current = controller;
    setState({ loading: true, result: null, error: '' });
    try {
      const result = await simulationApi.contactScreen(sceneRunId, {
        source_um: points[0].map(Number), return_um: points[1].map(Number),
        electrode_um: points[2].map(Number), reference_um: points[3].map(Number), clearance_um: clearance,
      }, controller.signal);
      if (!controller.signal.aborted && current.current === signature) setState({ loading: false, result, error: '', signature });
    } catch (error) {
      const status = error?.status ?? error?.response?.status;
      if (!controller.signal.aborted && current.current === signature) setState({ loading: false, result: null, signature,
        error: status === 429 ? 'Другая проверка ещё выполняется.'
          : status === 409 ? 'Индекс не соответствует выбранному графу.'
          : status === 503 ? 'Проверенный индекс контактов пока недоступен.'
          : status === 404 ? 'Проверка контактов недоступна на этом сервере.'
          : 'Не удалось проверить контакты. Повторите запрос.' });
    } finally { if (pending.current === controller) pending.current = null; }
  };
  const result = state.signature === signature ? state.result : null;
  const error = state.signature === signature ? state.error : '';
  const rows = result?.potential_intersections || [];
  const contacts = [...new Set(rows.flatMap(row => row.contact_indices))].sort((a, b) => a - b);
  const selectedContact = contacts.includes(Number(contact)) ? Number(contact) : contacts[0];
  const findAlternatives = async distance => {
    const selected = selectedContact;
    if (!contacts.includes(selected) || disabled || alternatives.loading) return;
    const origin = points[selected].map(Number);
    const paired = points[selected ^ 1].map(Number);
    setSearchDistance(distance);
    const candidates = [0, 1, 2].flatMap(axis => [-distance, distance].map(offset => origin.map(
      (value, i) => value + (i === axis ? offset : 0),
    ))).filter(point => Math.hypot(...point.map((value, i) => value - paired[i])) > 2 * clearance);
    if (!candidates.length) {
      setAlternatives({ loading: false, positions: [], error: '' });
      return;
    }
    const controller = new AbortController(); pendingAlternatives.current = controller;
    setAlternatives({ loading: true, positions: null, error: '' });
    try {
      const response = await simulationApi.contactPositions(sceneRunId, {
        positions_um: candidates, clearance_um: clearance,
      }, controller.signal);
      const blocked = new Set(response.potential_intersections.flatMap(row => row.contact_indices));
      if (!controller.signal.aborted && current.current === signature) {
        setAlternatives({ loading: false, positions: candidates.filter((_, i) => !blocked.has(i)), error: '' });
      }
    } catch (error) {
      if (!controller.signal.aborted && current.current === signature) {
        setAlternatives({ loading: false, positions: null, error: (error?.status ?? error?.response?.status) === 429
          ? 'Другая проверка ещё выполняется.' : 'Не удалось проверить варианты. Повторите поиск.' });
      }
    } finally { if (pendingAlternatives.current === controller) pendingAlternatives.current = null; }
  };
  return <Box mt={3}>
    <Button type="button" size="sm" variant="outline" isLoading={state.loading}
      isDisabled={!valid || disabled || alternatives.loading} onClick={screen}>Проверить контакты</Button>
    {!result && !error && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>
      {state.loading ? 'Проверка контактов выполняется…' : 'Проверка расположения по всем доступным морфологиям не выполнена.'}
    </Text>}
    {error && <Text role="alert" fontSize="12px" color="orange.200" mt={1}>{error}</Text>}
    {result && <Text role={rows.length ? 'alert' : 'status'} fontSize="12px"
      color={rows.length ? 'orange.200' : SIMULATION_THEME.textSecondary} mt={1}>
      {rows.length
        ? `Возможное пересечение: ${contacts.map(index => names[index]).join(', ')}; клеток — ${rows.length}. Измените положение контактов и повторите проверку.`
        : 'В проверенном снимке пересечения не найдены. Совмещение с телом и свойства тканей не подтверждены.'}
    </Text>}
    {result && rows.length > 0 && onSelectContact && <Box mt={2}>
      <HStack flexWrap="wrap">
        <ButtonGroup size="sm" isAttached aria-label="Контакт для поиска положения">
          {contacts.map(index => <Button key={index} type="button" aria-pressed={index === selectedContact}
            variant={index === selectedContact ? 'solid' : 'outline'} isDisabled={disabled || alternatives.loading}
            onClick={() => { setContact(String(index)); setSearchDistance(25); setAlternatives({ loading: false, positions: null, error: '' }); }}>{names[index]}</Button>)}
        </ButtonGroup>
        <Button type="button" size="sm" variant="outline" isDisabled={disabled} isLoading={alternatives.loading}
          onClick={() => findAlternatives(25)}>Проверить соседние точки</Button>
      </HStack>
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>До шести точек на расстоянии {searchDistance} мкм в системе MaleCNS. Поверхность тела и ткани не проверяются.</Text>
      {alternatives.error && <Text role="alert" fontSize="12px" color="orange.200">{alternatives.error}</Text>}
      {alternatives.positions && <Box mt={2}>
        <Text role="status" fontSize="12px">{alternatives.positions.length ? 'Без пересечений в проверенном снимке:' : 'Среди соседних точек подходящих не найдено.'}</Text>
        {!alternatives.positions.length && searchDistance < 250 && <Button type="button" size="xs" variant="outline" mt={1} isDisabled={disabled}
          onClick={() => findAlternatives(searchDistance === 25 ? 100 : 250)}>Проверить дальше · {searchDistance === 25 ? 100 : 250} мкм</Button>}
        <HStack flexWrap="wrap" mt={1}>{alternatives.positions.map((point, index) => <Button key={index} size="xs" type="button" variant="outline" isDisabled={disabled}
          onClick={() => onSelectContact(selectedContact, point)}>{point.map(value => Number(value.toFixed(2))).join(' / ')}</Button>)}</HStack>
        <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>После выбора повторите проверку всех контактов.</Text>
      </Box>}
    </Box>}
  </Box>;
}
