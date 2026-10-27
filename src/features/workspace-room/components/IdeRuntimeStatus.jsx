import { useLayoutEffect, useRef } from 'react';
import { Button, Icon, Popover, PopoverBody, PopoverCloseButton, PopoverContent,
  PopoverHeader, PopoverTrigger, Portal, Text, useDisclosure } from '@chakra-ui/react';
import { FiClock } from '@shared/icons';
import { borderRadius, colors, layers } from '@theme/tokens';
import { IDE_RUNTIME_LABELS } from '../model/ideReadContracts';

const DETAILS = {
  ready: 'Файлы находятся в отдельной временной среде этого репозитория. Запись в среду не является долговечным снимком или Git-коммитом.',
  expired: 'Временная среда завершена. Сохранённый проект можно восстановить из истории. Новая пустая среда автоматически не создаётся; загруженный текст остаётся доступен для копирования.',
  unknown: 'Состояние существующей среды не подтверждено. Обновление IDE только проверяет её; новый пустой проект вместо неё не создаётся.',
  unavailable: 'Не удалось проверить среду. Уже загруженные исходники остаются доступны; обновите IDE, чтобы повторить чтение.',
  rejected: 'Запуск среды отклонён. Доступные действия восстановления показаны в рабочей области; открытие этой справки не повторяет запуск.',
  not_created: 'Проект зарегистрирован, но рабочая среда ещё не создана. Её запуск не вызывает ИИ.',
  pending: 'Подготовка отдельной среды ещё не подтверждена. Проверяется тот же запуск, без создания второй среды.',
  dispatching: 'Запрос на подготовку отдельной среды принят. Готовность пока не подтверждена.',
};

/** Passive details, not another runtime observer or provisioning action. */
export default function IdeRuntimeStatus({ runtime, loading }) {
  const { isOpen, onOpen, onClose } = useDisclosure();
  const closeRef = useRef(null);
  useLayoutEffect(() => {
    if (isOpen) closeRef.current?.focus({ preventScroll: true });
  }, [isOpen]);
  const state = runtime?.state;
  const label = loading ? 'Проверяю среду…' : IDE_RUNTIME_LABELS[state] || 'Состояние среды не получено';
  const warning = ['expired', 'unavailable', 'unknown', 'rejected'].includes(state);
  return <Popover placement="bottom-start" isOpen={isOpen} onOpen={onOpen} onClose={onClose} initialFocusRef={closeRef}>
    <PopoverTrigger>
      <Button size="document" variant="ghost" px={2} gap={1.5} flexShrink={0}
        aria-label={`Состояние среды: ${label}`} title="Сведения о временной среде" onClick={onOpen}>
        <Icon as={FiClock} boxSize={3.5} color={warning ? colors.warning : colors.fg[3]} />
        <Text as="span" role="status" aria-atomic="true" fontSize="xs" color={warning ? colors.warning : colors.fg[3]}>{label}</Text>
      </Button>
    </PopoverTrigger>
    <Portal>
      {isOpen && <PopoverContent bg={colors.bg.menu} borderColor={colors.border.strong} borderRadius={borderRadius.md}
        motionProps={{ animate: false }} style={{ visibility: 'visible', opacity: 1, transform: 'none' }}
        w="280px" maxW="calc(100vw - 24px)" maxH="min(360px, 70dvh)" overflowY="auto" zIndex={layers.popover}>
        <PopoverHeader fontSize="13px" fontWeight={600} border={0} pr={12}>Среда проекта</PopoverHeader>
        <PopoverCloseButton ref={closeRef} aria-label="Закрыть сведения о среде" />
        <PopoverBody pt={1} pb={3}>
          <Text fontSize="12px" color={colors.fg[2]} lineHeight={1.5}>{loading
            ? 'Проверяется текущая среда. Эта справка не запускает новую среду и не вызывает ИИ.'
            : DETAILS[state] || 'Сведения пока не получены. Обновите IDE, чтобы проверить состояние.'}</Text>
        </PopoverBody>
      </PopoverContent>}
    </Portal>
  </Popover>;
}
