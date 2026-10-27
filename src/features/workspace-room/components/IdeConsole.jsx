import { useId } from 'react';
import { Box, Button, Flex, HStack, Icon, Input, Text } from '@chakra-ui/react';
import { FiChevronDown, FiPlay, FiTerminal, FiTrash2 } from '@shared/icons';
import { colors, documentControls } from '@theme/tokens';

// eslint-disable-next-line no-control-regex -- Strip terminal control bytes; never interpret ANSI as browser markup.
const plain = value => value?.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '') || '';

const stages = { preparing: 'Сохраняется снимок…', ready: 'Подготовка запуска…',
  dispatching: 'Подготовка запуска…', running: 'Команда выполняется…', stopping: 'Остановка…',
  unknown: 'Состояние процесса не подтверждено. Повторный запуск запрещён.',
  completed: 'Команда завершена', failed: 'Команда не подтвердила результат', cancelled: 'Команда остановлена' };
const checks = { passed: 'Проверка версии запуска пройдена', failed: 'Проверка не пройдена',
  blocked: 'Проверка заблокирована', not_requested: 'Проверка критерия не запрашивалась' };
const blockers = { preparation_failed: 'Снимок не подтверждён. Команда не запускалась.',
  runtime_unavailable: 'Нужная среда выполнения недоступна.', output_unavailable: 'Необходимый вывод не сохранён.',
  source_revision_unavailable: 'Итоговую версию файлов проверить не удалось.',
  deadline_exceeded: 'Лимит времени исчерпан.', binding_changed: 'Версия среды изменилась.',
  verification_failed: 'Ожидаемый результат не подтверждён.',
  empty_test_suite: 'Нет выполненных тестов: набор пуст или все тесты пропущены.',
  expected_output_missing: 'Не задан ожидаемый вывод скрипта.', unexpected_output: 'Вывод отличается от ожидаемого.',
  command_timeout: 'Время выполнения команды истекло.', verification_unavailable: 'Результат тестов не подтверждён.' };
const blockerFor = entry => Object.hasOwn(blockers, entry.checkReason) ? blockers[entry.checkReason]
  : Object.hasOwn(blockers, entry.blocker) ? blockers[entry.blocker] : '';

export default function IdeConsole({ console: terminal, blocked, unavailable, dirty, onCollapse }) {
  const id = useId();
  const disabled = Boolean(blocked || unavailable || terminal.busy);
  return <Flex data-testid="ide-console" as="section" aria-label="Консоль разработчика" direction="column" minH={0} minW={0} h="full" bg={colors.ink[900]}>
    <HStack px={2} spacing={1} flexShrink={0} h={`${documentControls.desktop}px`} borderBottom="1px solid" borderColor={colors.border.subtle}>
      <Icon as={FiTerminal} boxSize={3.5} color={colors.fg[3]} />
      <Text as="h2" fontSize="xs" flex={1}>Консоль</Text>
      <Button size="document" variant="ghost" minW="34px" px={2} aria-label="Очистить вывод консоли" title="Очистить вывод консоли"
        isDisabled={Boolean(terminal.busy) || !terminal.entries.length} onClick={terminal.clear}><Icon as={FiTrash2} boxSize={3.5} /></Button>
      <Button size="document" variant="ghost" minW="34px" px={2} aria-label="Свернуть консоль" title="Свернуть консоль" onClick={onCollapse}><Icon as={FiChevronDown} boxSize={3.5} /></Button>
    </HStack>
    <Box flex={1} minH={0} overflow="auto" px={3} py={2} tabIndex={0} aria-label="Вывод команд" fontFamily="mono" fontSize="12px" overscrollBehavior="contain">
      {terminal.agentError && <Box mb={2} fontFamily="body">
        <Text fontSize="xs" color={colors.warning}>Не удалось прочитать команды агента. Сохранённый вывод не изменён.</Text>
        <Button size="document" variant="ghost" onClick={terminal.checkAgent}>Проверить команды агента</Button>
      </Box>}
      {!terminal.entries.length && <Text color={colors.fg[3]} fontFamily="body" fontSize="xs">Команды запускаются из корня проекта. Каждый запуск — отдельный процесс.</Text>}
      {terminal.entries.map(entry => <Box key={entry.id} mb={3}>
        <Text color={colors.fg[2]} whiteSpace="pre-wrap" overflowWrap="anywhere">$ {entry.command}</Text>
        {entry.source === 'agent' && <Text fontFamily="body" fontSize="xs" color={colors.fg[3]} role="status">
          {stages[entry.state]}{entry.verification ? ` · ${checks[entry.verification]}` : ''}
        </Text>}
        {entry.source === 'agent' && blockerFor(entry)
          && <Text fontFamily="body" fontSize="xs" color={colors.warning}>{blockerFor(entry)}</Text>}
        {entry.source === 'agent' && !['completed', 'failed', 'cancelled'].includes(entry.state)
          && <Button size="document" variant="ghost" onClick={() => terminal.check(entry.id)}>Проверить состояние</Button>}
        {entry.result ? <>
          {entry.result.stdout && <Text as="pre" m={0} whiteSpace="pre-wrap" overflowWrap="anywhere">{plain(entry.result.stdout)}</Text>}
          {entry.result.stderr && <Text as="pre" m={0} color={colors.warning} whiteSpace="pre-wrap" overflowWrap="anywhere">{plain(entry.result.stderr)}</Text>}
          <Text fontFamily="body" fontSize="xs" color={entry.result.exit_code === 0 ? colors.fg[3] : colors.warning} role="status">
            {entry.result.timed_out ? 'Превышено время выполнения' : `Код завершения: ${entry.result.exit_code}`}
            {entry.result.truncated ? ' · Вывод сокращён' : ''}
          </Text>
        </> : entry.source === 'agent' ? null : <HStack align="start" flexWrap="wrap" spacing={1}>
          <Text fontFamily="body" fontSize="xs" color={colors.fg[3]} role="status">
            {terminal.busy === 'run' && entry === terminal.entries.at(-1) ? 'Выполняется…'
              : 'Результат пока не получен. Команда не будет повторена автоматически.'}
          </Text>
          {!terminal.busy && <Button size="document" variant="ghost" onClick={() => terminal.check(entry.id)}>Проверить результат</Button>}
        </HStack>}
      </Box>)}
    </Box>
    <Box as="form" noValidate px={2} pt={1} pb={{ base: 'calc(8px + var(--app-safe-bottom, 0px))', md: 'calc(2px + var(--app-safe-bottom, 0px))' }} minW={0} flexShrink={0} borderTop="1px solid" borderColor={colors.border.subtle}
      onSubmit={event => { event.preventDefault(); void terminal.run(); }}>
      {(unavailable || dirty || blocked) && <Text id={`${id}-help`} px={1} pb={1} fontSize="xs" color={colors.fg[3]}>
        {unavailable ? 'Для запуска нужна доступная среда проекта.' : dirty ? 'Команда использует сохранённые файлы, не текст редактора.' : 'Дождитесь завершения текущей операции.'}
      </Text>}
      <HStack spacing="8px" minW={0}>
        <Text aria-hidden="true" color={colors.fg[3]} flexShrink={0}>$</Text>
        <Input value={terminal.draft} onChange={event => terminal.setDraft(event.target.value)}
          aria-label="Команда консоли" placeholder="Команда…" title="Например, python src/hello_world.py" size="sm" variant="unstyled" fontFamily="mono"
          maxLength={8192} autoComplete="off" spellCheck={false} minW={0} w={0} flex={1} h="34px"
          aria-describedby={(unavailable || dirty || blocked) ? `${id}-help` : undefined}
          onKeyDown={event => { if (event.key === 'Enter' && (event.nativeEvent.isComposing || event.keyCode === 229)) event.preventDefault(); }} />
        <Button type="submit" size="document" variant="ghost" aria-label="Выполнить команду" title="Выполнить команду" minW="34px" px={2}
          isDisabled={disabled || !terminal.draft.trim()} aria-busy={terminal.busy === 'run'}><Icon as={FiPlay} boxSize={3.5} /></Button>
      </HStack>
      {terminal.error && <Text role="alert" fontSize="xs" color={colors.warning}>{terminal.error}</Text>}
    </Box>
  </Flex>;
}
