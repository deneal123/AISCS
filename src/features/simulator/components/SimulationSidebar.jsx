import React from 'react';
import { AlertDialog, AlertDialogBody, AlertDialogContent, AlertDialogFooter, AlertDialogHeader, AlertDialogOverlay, Box, Button, CloseButton, Flex, HStack, IconButton, Stack, Text } from '@chakra-ui/react';
import { BiTestTube } from 'react-icons/bi';
import { FiPlus, FiTrash2 } from 'react-icons/fi';
import { SIMULATION_THEME } from '../theme';

const states = { queued: 'В очереди', preparing: 'Подготовка', running: 'Расчёт', publishing: 'Сохранение', completed: 'Завершён', cancelling: 'Остановка', cancelled: 'Остановлен', failed: 'Ошибка' };
const labels = { none: 'Нет воздействия', weak: 'Слабое воздействие', strong: 'Сильное воздействие' };

export default function SimulationSidebar({ history, modelId, selectedId, onNew, onSelect, onClose, onRemove }) {
  const [candidate, setCandidate] = React.useState(null);
  const [removing, setRemoving] = React.useState(false);
  const [removeError, setRemoveError] = React.useState('');
  const cancelRef = React.useRef();
  const runs = history.runs.filter(item => item.configuration?.model_id === modelId);
  return <Flex as="aside" aria-label="Опыты" position={{ base: 'absolute', md: 'relative' }} zIndex={4} h="full" w={{ base: '240px', lg: '260px' }} flexShrink={0} direction="column" bg={SIMULATION_THEME.sidebarBg} borderRight="1px solid" borderColor={SIMULATION_THEME.panelBorder} p={3}>
    <HStack justify="space-between" mb={3}><Text fontSize="11px" color="#7B9DFF" letterSpacing=".16em" fontWeight="600">ОПЫТЫ</Text>
      <CloseButton display={{ base: 'inline-flex', md: 'none' }} size="sm" aria-label="Закрыть список опытов" onClick={onClose} /></HStack>
    <Button leftIcon={<FiPlus />} variant="outline" colorScheme="blue" justifyContent="start" size="sm" onClick={onNew}>Новый опыт</Button>
    <Stack mt={4} spacing={1} overflowY="auto" flex={1}>
      {!runs.length && <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} p={2}>Сохранённых опытов ЦНС пока нет</Text>}
      {runs.map(item => <HStack key={item.id} spacing={0} bg={item.id === selectedId ? SIMULATION_THEME.panelActive : undefined} borderRadius="md"><Button flex="1" minW={0} data-run-id={item.id} size="sm" variant="ghost" h="auto" minH="48px" justifyContent="start" whiteSpace="normal" leftIcon={<BiTestTube />} onClick={() => onSelect(item)}>
        <Box textAlign="left"><Text fontSize="13px">{labels[item.configuration?.stimulus] || item.title || 'Опыт'}</Text><Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>{states[item.state] || item.state} · {new Date(item.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</Text></Box>
      </Button><IconButton size="sm" variant="ghost" icon={<FiTrash2 />} aria-label={`Удалить из списка: ${item.title || 'опыт'}`} isDisabled={!['completed', 'failed', 'cancelled'].includes(item.state)} onClick={() => { setRemoveError(''); setCandidate(item); }} /></HStack>)}
      {history.error && <Text role="alert" fontSize="12px" color="red.200">{history.error}</Text>}
      {(history.nextOffset !== null || history.error) && <Button size="sm" variant="outline" isLoading={history.loading} onClick={history.error ? history.retry : history.more}>{history.error ? 'Повторить загрузку опытов' : 'Ещё опыты'}</Button>}
    </Stack>
    <AlertDialog isOpen={Boolean(candidate)} leastDestructiveRef={cancelRef} onClose={() => { if (!removing) setCandidate(null); }} isCentered>
      <AlertDialogOverlay><AlertDialogContent bg={SIMULATION_THEME.sidebarBg} color="white">
        <AlertDialogHeader fontSize="md">Удалить опыт из списка?</AlertDialogHeader>
        <AlertDialogBody>Опыт исчезнет из списка. Связанные расчёты и файлы останутся в хранилище.</AlertDialogBody>
        {removeError && <Text role="alert" color="red.200" px={6} pt={2} fontSize="sm">{removeError}</Text>}
        <AlertDialogFooter><Button ref={cancelRef} onClick={() => setCandidate(null)} isDisabled={removing}>Отмена</Button>
          <Button colorScheme="red" ml={3} isLoading={removing} onClick={async () => { setRemoving(true); setRemoveError(''); try { await onRemove(candidate); setCandidate(null); } catch { setRemoveError('Не удалось удалить опыт из списка. Повторите попытку.'); } finally { setRemoving(false); } }}>Удалить</Button></AlertDialogFooter>
      </AlertDialogContent></AlertDialogOverlay>
    </AlertDialog>
  </Flex>;
}
