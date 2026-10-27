import { Button, Flex, HStack, Text } from '@chakra-ui/react';
import { colors } from '@theme/tokens';

const labels = {
  preparing: 'Подготовка клонирования не завершена.',
  blocked: 'Среда клона пока недоступна.',
  running: 'Клонирование выполняется. Восстановлено наблюдение, не повторный запуск.',
  failed: 'Клонирование не завершено. Исходные файлы сохранены.',
  unconfirmed: 'Результат клонирования не подтверждён. Git-запись не повторяется.',
  complete: 'Клонирование завершено.',
};

export default function IdeCloneRecoveryBar({ recovery, repositoryId, disabled, onResume, onOpen, onNew }) {
  const attempt = recovery.attempt;
  if (!recovery.error && (!attempt || (attempt.state === 'complete' && !recovery.completed))) return null;
  const blocked = Boolean(disabled || recovery.loading);
  return <Flex data-testid="ide-clone-recovery" px={3} py={2} gap={2} align="center" flexWrap="wrap"
    flexShrink={0} borderBottom="1px solid" borderColor={colors.border.subtle}>
    <Text fontSize="xs" color={colors.fg[3]} flex="1" minW="160px" role={recovery.error ? 'alert' : 'status'}>
      {recovery.error ? 'Не удалось проверить прежнее клонирование. Повторите чтение перед новой попыткой.'
        : <>{labels[attempt.state]} <Text as="span" title={attempt.repository.name}>{attempt.repository.name}</Text>
          {recovery.observationExpired && ' Автонаблюдение остановлено; проверьте результат вручную.'}
          {!attempt.request && attempt.state === 'preparing' && ' Исходные параметры недоступны; повторная запись не запускается.'}</>}
    </Text>
    <HStack spacing={2} flexWrap="wrap">
      <Button size="document" variant="workbenchSecondary" isDisabled={blocked} onClick={() => recovery.refresh()}>Проверить клонирование</Button>
      {!recovery.error && attempt?.request && ['preparing', 'blocked'].includes(attempt.state)
        && <Button size="document" variant="workbenchSecondary" isDisabled={blocked} onClick={onResume}>Продолжить…</Button>}
      {!recovery.error && attempt?.repository.repository_id !== repositoryId
        && <Button size="document" variant="workbenchSecondary" isDisabled={blocked} onClick={onOpen}>Открыть проект клона</Button>}
      {!recovery.error && attempt && ['failed', 'unconfirmed'].includes(attempt.state)
        && <Button size="document" variant="ghost" isDisabled={blocked} onClick={onNew}>Другой репозиторий</Button>}
    </HStack>
  </Flex>;
}
