import { Flex, HStack, Icon, Text } from '@chakra-ui/react';
import { FiCode } from '@shared/icons';
import WorkbenchInfoPopover from '@shared/controls/WorkbenchInfoPopover';
import { colors } from '@theme/tokens';

/** Permanent slot for Chat's single composer/trace owner, not another chat. */
export default function IdeAgentPane({ assistantRef, name, statusHint }) {
  return <Flex as="aside" aria-label="Агент IDE" data-testid="ide-agent-pane" direction="column" h="full" minH={0} minW={0}
    bg={colors.bg.card}>
    <HStack px={3} py={2} spacing={2} flexShrink={0} borderBottom="1px solid" borderColor={colors.border.subtle}>
      <Icon as={FiCode} boxSize={3.5} color={colors.fg[3]} />
      <Text as="h2" fontSize="xs" fontWeight={600}>Агент</Text>
      <Text ml="auto" fontSize="11px" color={colors.fg[3]}>Запросы за кредиты</Text>
      <WorkbenchInfoPopover label="Об агенте IDE" title="Работа агента" closeLabel="Закрыть сведения об агенте">
        <Text mb={2}>Агент читает и меняет файлы репозитория «{name}». Запросы расходуют кредиты; действуют тарифы и лимиты аккаунта.</Text>
        <Text>Подсказки только заполняют сообщение. Отправка, запуск скриптов и публикация в Git — отдельные действия.</Text>
      </WorkbenchInfoPopover>
    </HStack>
    {statusHint && <Text px={3} py={2} flexShrink={0} fontSize="xs" color={colors.warning} role="status">{statusHint}</Text>}
    <Flex ref={assistantRef} flex="1" direction="column" minH={0} minW={0} overflow="hidden" />
  </Flex>;
}
