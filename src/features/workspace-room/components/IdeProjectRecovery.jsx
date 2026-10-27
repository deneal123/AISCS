import { Box, Button, Text } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';

/** Expiry guidance belongs to the file pane, never another persistent toolbar. */
export default function IdeProjectRecovery({ saved, onOpenHistory = saved.show }) {
  const hasHistory = Boolean(saved.history?.items.length || saved.intent || saved.history?.last_restore);
  const hasVersion = saved.history?.items.some(item => item.state === 'published');
  return <Box as="section" aria-label="Восстановление проекта" px={3} py={4}>
    <Text as="h3" fontSize="sm" fontWeight="semibold">Среда завершена</Text>
    {saved.loading ? <Box mt={2}><AppLoading label="Проверяю сохранённые версии…" /></Box>
      : saved.error ? <>
        <Text mt={2} fontSize="xs" color={colors.fg[3]}>Не удалось проверить сохранённые версии.</Text>
        <Button mt={3} size="document" variant="workbenchSecondary" isDisabled={Boolean(saved.busy)} onClick={saved.load}>Повторить проверку</Button>
      </> : <>
        <Text mt={2} fontSize="xs" color={colors.fg[3]}>{hasVersion
          ? 'Откройте сохранённую версию в новой среде.'
          : hasHistory ? 'Проверьте результат предыдущего сохранения в истории.'
            : !saved.available ? 'История сохранённых версий сейчас недоступна.'
            : 'Сохранённых версий нет.'}</Text>
      </>}
    {saved.available && hasHistory && !saved.error && <Button mt={3} size="document" variant="workbenchPrimary"
      aria-busy={Boolean(saved.loading)} isDisabled={Boolean(saved.busy)} onClick={onOpenHistory}>Открыть историю</Button>}
  </Box>;
}
