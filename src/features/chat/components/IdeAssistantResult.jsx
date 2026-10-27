import { useId } from 'react';
import { Box, Button, Text, VisuallyHidden } from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { latestTimelineMessage } from '../utils/latestTimelineMessage';
import { presentTaskResult } from '../model/taskResult';

function compactSummary(value) {
  if (typeof value !== 'string' || value.trim() !== value) return null;
  if (value === 'Подтверждённых записей в файлы нет. Подробности запроса — в чате.') return null;
  const chars = [...value];
  return chars.length > 0 && chars.length <= 280 && !chars.some(char => {
    const code = char.codePointAt(0);
    return code < 32 || code === 127 || code === 0x2028 || code === 0x2029;
  }) ? value : null;
}

export default function IdeAssistantResult({ messages = [], composerRef }) {
  const helpId = useId();
  const reply = latestTimelineMessage(messages, message => message.type === 'agent' || message.type === 'assistant');
  const taskResult = presentTaskResult(reply?.metadata?.task_result);
  return <Box flex="1" minH={0} overflowY="auto" overscrollBehavior="contain" px={3} py={4} data-testid="ide-agent-result">
    {reply ? <>
      <Text as="h3" fontSize="sm" fontWeight={600} mb={2}>Итог запроса</Text>
      <Text fontSize="sm" overflowWrap="anywhere" mb={3} data-testid="ide-agent-summary">
        {compactSummary(reply.metadata?.ide_summary) || 'Краткий итог недоступен. Полный ответ — в чате.'}
      </Text>
      {taskResult && <Text fontSize="xs" color={taskResult.status === 'completed' ? colors.fg[3] : colors.warning}
        overflowWrap="anywhere" mb={3} data-testid="ide-task-result">
        {taskResult.title}. {taskResult.detail}
      </Text>}
      {(reply.metadata?.ide_write_unconfirmed || Number.isInteger(reply.metadata?.ide_files_written)) && <Text fontSize="xs" color={reply.metadata?.ide_write_unconfirmed ? colors.warning : colors.fg[3]} mb={3} role="status">
        {reply.metadata?.ide_write_unconfirmed ? 'Результат записи не подтверждён. Проверьте файлы перед повторной правкой.'
          : Number.isInteger(reply.metadata?.ide_files_written) && reply.metadata.ide_files_written > 0
            ? `Подтверждено записей в среду: ${reply.metadata.ide_files_written}. Это не Git-коммит.`
            : reply.metadata?.ide_files_written === 0 ? 'Файлы в этом запросе не изменены.' : null}
      </Text>}
    </> : <>
      <Text as="h3" fontSize="sm" fontWeight={600} mb={3}>Что сделаем?</Text>
      <VisuallyHidden id={helpId}>Подсказки только заполняют сообщение. Отправка — отдельное действие.</VisuallyHidden>
      <Box display="flex" flexWrap="wrap" gap={1.5}>
        {[['Структура', 'Объясни структуру проекта'], ['README', 'Добавь README с инструкцией запуска'], ['Проверить код', 'Найди возможные ошибки в коде']].map(([label, text]) => <Button key={text} size="document" variant="workbenchSecondary"
          maxW="full" aria-label={text} aria-describedby={helpId} title={`Заполнить сообщение: ${text}`}
          onClick={() => composerRef?.current?.setInputValue(text)}>{label}</Button>)}
      </Box>
    </>}
  </Box>;
}
