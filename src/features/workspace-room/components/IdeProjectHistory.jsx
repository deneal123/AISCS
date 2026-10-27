import { useEffect, useRef, useState } from 'react';
import { Box, Button, Flex, HStack, Icon, Modal, ModalBody, ModalCloseButton, ModalContent, ModalFooter, ModalHeader, ModalOverlay, Text } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { FiTrash2, FiX } from '@shared/icons';
import { colors } from '@theme/tokens';

const size = value => {
  const scale = value >= 1073741824 ? 3 : value >= 1048576 ? 2 : value >= 1024 ? 1 : 0;
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value / (1024 ** scale))} ${['Б', 'КБ', 'МБ', 'ГБ'][scale]}`;
};
const date = value => new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));

export default function IdeProjectHistory({ saved, name, blocked, onRestore, onClose, finalFocusRef }) {
  const [confirm, setConfirm] = useState(null);
  const cancel = useRef(null);
  const closeControl = useRef(null);
  const confirmTrigger = useRef(null);
  const actionRefs = useRef(new Map());
  const returnAfterAction = useRef(false);
  useEffect(() => {
    if (confirm) cancel.current?.focus();
    else if (!saved.busy && returnAfterAction.current) { returnAfterAction.current = false; closeControl.current?.focus(); }
    else if (!saved.busy && confirmTrigger.current) (actionRefs.current.get(confirmTrigger.current) || closeControl.current)?.focus();
  }, [confirm, saved.busy]);
  const history = saved.history;
  const disabled = Boolean(saved.busy || saved.loading || blocked);
  const pendingRestore = history?.last_restore?.state === 'pending';
  const canRestore = history?.runtime.state === 'expired' && !saved.intent && !pendingRestore;
  const close = () => { if (!saved.busy) { if (confirm) setConfirm(null); else onClose(); } };
  const actionRef = (kind, id) => element => { const key = `${kind}:${id}`; if (element) actionRefs.current.set(key, element); else actionRefs.current.delete(key); };
  const choose = (kind, item) => { confirmTrigger.current = `${kind}:${item.checkpoint_id}`; setConfirm({ kind, item }); };
  const commit = () => {
    const { kind, item } = confirm; returnAfterAction.current = true; setConfirm(null);
    if (kind === 'discard') void saved.discard(item);
    else if (kind === 'abandon') void saved.abandon(item);
    else onRestore(() => { void saved.restore(item); });
  };
  const discarding = confirm?.kind === 'discard';
  const abandoning = confirm?.kind === 'abandon';
  const destructive = discarding || abandoning;
  const inspected = saved.inspected && saved.inspected.state !== 'published' && !saved.inspected.collected ? saved.inspected : null;
  const listedIntent = history?.items.some(item => item.checkpoint_id === saved.intent?.checkpoint_id);
  const listedInspection = history?.items.some(item => item.checkpoint_id === inspected?.checkpoint_id);
  const discardButton = item => <Button ref={actionRef('discard', item.checkpoint_id)} size="document" variant="ghost" px={2} minW="34px"
    aria-label="Удалить незавершённый снимок" title="Удалить только незавершённый снимок"
    isDisabled={disabled} onClick={() => choose('discard', item)}><Icon as={FiTrash2} boxSize={3.5} /></Button>;
  const abandonButton = item => <Button ref={actionRef('abandon', item.checkpoint_id)} size="document" variant="ghost" px={2} minW="34px"
    aria-label="Отменить попытку сохранения" title="Отменить попытку, не удаляя файлы проекта"
    isDisabled={disabled} onClick={() => choose('abandon', item)}><Icon as={FiX} boxSize={3.5} /></Button>;
  return <Modal isOpen={saved.open} onClose={close} finalFocusRef={finalFocusRef} isCentered motionPreset="none">
    <ModalOverlay /><ModalContent mx={3} maxW="440px" overflow="hidden" bg={colors.bg.menu} borderWidth="1px" borderColor={colors.border.strong}>
      <ModalHeader fontSize="md" pr={12} pb={2}>{abandoning ? 'Отменить попытку сохранения?' : discarding ? 'Удалить незавершённый снимок?' : confirm ? 'Восстановить проект?' : 'История проекта'}
        <Text mt={1} fontSize="xs" fontWeight="normal" color={colors.fg[3]} isTruncated>{name}</Text>
      </ModalHeader><ModalCloseButton ref={closeControl} aria-label={confirm ? 'Вернуться к истории' : 'Закрыть историю проекта'} isDisabled={Boolean(saved.busy)} />
      <ModalBody minH={0} overflowY="auto" pb={4}>
        {saved.busy && <AppLoading label={saved.busy === 'abandon' ? 'Отменяю попытку сохранения…' : saved.busy === 'discard' ? 'Удаляю незавершённый снимок…' : saved.busy === 'restore' || saved.busy === 'check-restore' ? 'Восстанавливаю проект…' : saved.busy === 'save' ? 'Сохраняю проект…' : 'Проверяю результат…'} />}
        {confirm ? <Text fontSize="sm">{abandoning ? 'Эта попытка больше не станет сохранённой версией. Файлы проекта не изменятся. Загрузка может завершиться в фоне; место останется занятым до очистки.'
          : discarding ? `${confirm.item.created_at ? `Незавершённый снимок от ${date(confirm.item.created_at)}` : 'Этот незавершённый снимок'} будет удалён. Файлы проекта и сохранённые версии останутся без изменений.`
          : `Снимок от ${date(confirm.item.created_at)} откроется в новой временной среде. Предыдущие сохранённые версии останутся в истории.`}</Text> : <>
          {saved.loading && <AppLoading label="Загружаю историю…" />}
          {saved.error && <Box role="alert" mb={3}><Text fontSize="sm" color={colors.warning}>{saved.error}</Text>
            <Button mt={2} size="document" variant="workbenchSecondary" isDisabled={disabled} onClick={saved.load}>Обновить историю</Button>
          </Box>}
          {saved.outcome && <Text role="status" fontSize="sm" mb={3}>{saved.outcome}</Text>}
          {saved.intent && !listedIntent && <Box mb={3} p={3} borderWidth="1px" borderColor={colors.border.subtle} borderRadius="control">
            <Text fontSize="sm">{saved.intent.kind === 'save' ? 'Проверить последнее сохранение' : 'Проверить последнее восстановление'}</Text>
            <HStack mt={2} spacing={2} flexWrap="wrap">
              <Button size="document" variant="workbenchSecondary" isDisabled={disabled} onClick={saved.intent.kind === 'save' ? () => saved.check() : saved.checkRestore}>Проверить результат</Button>
              {saved.intent.generation || saved.intent.base_generation ? <Button size="document" variant="ghost" isDisabled={disabled} onClick={saved.retry}>Повторить тот же запрос</Button> : null}
            </HStack>
          </Box>}
          {inspected && <Box mb={3} fontSize="xs" color={colors.fg[3]}>
            <Text>{inspected.can_discard ? 'Незавершённый снимок можно удалить, не затрагивая файлы проекта.'
              : 'Завершение загрузки не подтверждено. Для очистки нужно дождаться подтверждения.'}</Text>
            {!listedInspection && inspected.can_discard && discardButton(inspected)}
            {!listedInspection && !inspected.can_discard && inspected.can_abandon && abandonButton(inspected)}
            {listedIntent && saved.intent?.generation && <Button mt={1} size="document" variant="ghost" isDisabled={disabled} onClick={saved.retry}>Повторить тот же запрос</Button>}
          </Box>}
          {!saved.intent && pendingRestore && <Button mb={3} size="document" variant="workbenchSecondary" isDisabled={disabled} onClick={saved.checkRestore}>Проверить восстановление</Button>}
          {history && !history.items.length && !saved.loading && <Text py={4} fontSize="sm" color={colors.fg[3]}>Сохранённых версий пока нет. Запишите правки файлов в среду, затем сохраните проект.</Text>}
          <Box as="ul" listStyleType="none" m={0} p={0}>
            {history?.items.map(stored => {
              const item = saved.inspected?.checkpoint_id === stored.checkpoint_id ? { ...stored, ...saved.inspected } : stored;
              if (item.collected) return null;
              return <Flex as="li" key={item.checkpoint_id} py={2.5} gap={3} align="center" borderBottomWidth="1px" borderColor={colors.border.subtle}>
              <Box flex="1" minW={0}><Text fontSize="sm">{date(item.created_at)}</Text>
                <Text fontSize="xs" color={colors.fg[3]}>{item.state === 'pending' ? 'Сохранение не подтверждено' : ['retired', 'conflict'].includes(item.state) ? 'Ожидает очистки' : item.is_current ? 'Последний снимок' : 'Сохранённая версия'} · {size(item.size_bytes)}</Text>
              </Box>
              {item.state !== 'published' ? <HStack spacing={0} flexShrink={0}>
                <Button size="document" variant="ghost" isDisabled={disabled || Boolean(saved.intent && saved.intent.checkpoint_id !== item.checkpoint_id)} onClick={() => saved.check(item)}>Проверить</Button>
                {(saved.inspected?.checkpoint_id === item.checkpoint_id ? saved.inspected.can_discard : item.can_discard) && discardButton({ ...item, can_discard: true })}
                {!item.can_discard && item.can_abandon && abandonButton(item)}
              </HStack>
                : <Button ref={actionRef('restore', item.checkpoint_id)} size="document" variant="ghost" isDisabled={disabled || !canRestore} onClick={() => choose('restore', item)}>Восстановить</Button>}
            </Flex>;
            })}
          </Box>
          {history && <Text mt={3} fontSize="xs" color={colors.fg[4]}>
            {history.runtime.state !== 'expired' && history.items.some(item => item.state === 'published') && 'Восстановление доступно после завершения текущей среды. '}
            {size(history.usage.used_bytes)} из {size(history.usage.max_bytes)} · последний снимок и до 10 предыдущих версий.
            {history.truncated && ' Показаны последние 32 записи.'}
          </Text>}
        </>}
      </ModalBody>
      {confirm && <ModalFooter gap={2}>
        <Button ref={cancel} size="document" variant="workbenchSecondary" onClick={() => setConfirm(null)}>Отмена</Button>
        <Button size="document" variant={destructive ? 'solid' : 'workbenchPrimary'} colorScheme={destructive ? 'red' : undefined}
          isDisabled={disabled || (!destructive && !canRestore)} onClick={commit}>{abandoning ? 'Отменить попытку' : discarding ? 'Удалить снимок' : 'Восстановить'}</Button>
      </ModalFooter>}
    </ModalContent>
  </Modal>;
}
