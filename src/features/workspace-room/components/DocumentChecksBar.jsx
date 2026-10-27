import { Box, Button, HStack, Icon, Text } from '@chakra-ui/react';
import { FiActivity, FiAlertCircle, FiCheckCircle, FiChevronDown, FiClock } from '@shared/icons';
import { colors } from '@theme/tokens';
import { DocumentForgePanel, documentPipelineStages } from './DocumentForgePanel';

const COMPLETE = new Set(['пройден', 'Сохранён в Библиотеке']);
const CAUTION = new Set(['проверка требуется', 'Ожидает визуальной проверки', 'Ожидает сохранения в Библиотеку']);
const SUMMARY_LABELS = new Map([
  ['пройден', 'пройдена'], ['не запускался', 'не запускалась'],
  ['Сохранён в Библиотеке', 'сохранено'], ['не отправлялся', 'не сохранено'],
]);

export function DocumentChecksBar({ document, expanded, onToggle, scrollWithinPreview = false }) {
  const stages = documentPipelineStages(document.build, document.authoring);
  return <Box data-testid="pdf-checks-bar" borderTop="1px solid" borderColor={colors.border.subtle}
    flexShrink={0} maxH={expanded && !scrollWithinPreview ? '45%' : undefined} overflowY="auto" p={3}>
    <Button size="document" variant="ghost" px={1} leftIcon={<FiActivity />} aria-expanded={expanded}
      onClick={onToggle} rightIcon={<Icon as={FiChevronDown} transform={expanded ? 'rotate(180deg)' : undefined} />}>
      Проверки
    </Button>
    <HStack flexWrap="wrap" gap={3} pt={1} pb={1} aria-label="Краткий статус PDF">
      {[['Техническая', stages[2][1]], ['Визуальная', stages[3][1]], ['Библиотека', stages[4][1]]].map(([label, status]) => {
        const failed = status === 'Финал не удалось сохранить';
        const success = COMPLETE.has(status);
        const color = failed ? colors.error : success ? colors.success : CAUTION.has(status) ? colors.warning : colors.fg[3];
        return <HStack key={label} spacing={1.5} minW={0}>
          <Icon as={failed ? FiAlertCircle : success ? FiCheckCircle : FiClock} color={color} boxSize={3.5} flexShrink={0} />
          <Text fontSize="11px" color={colors.fg[3]}>{label}: <Text as="span" color={color}>
            {SUMMARY_LABELS.get(status) || status}
          </Text></Text>
        </HStack>;
      })}
    </HStack>
    {expanded && <Box pt={3}><DocumentForgePanel document={document} section="checks" previewVisible={false} previewActionVisible={false} /></Box>}
  </Box>;
}
