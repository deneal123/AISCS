import { Button, Icon, Text, Tooltip } from '@chakra-ui/react';
import { FiArrowRight } from '@shared/icons';
import { colors } from '@theme/tokens';
import './IdeMoveFileButton.css';

/** Density follows the file pane, not the viewport or the agent rail. */
export default function IdeMoveFileButton({ onClick, isDisabled }) {
  return <Tooltip label="Переместить файл или папку" openDelay={300} bg={colors.bg.menu}
    color={colors.fg[1]} border="1px solid" borderColor={colors.border.subtle}>
    <Button size="document" variant="ghost" aria-label="Переместить" px={2}
      minW={{ base: '30px', md: '34px' }} flexShrink={0} isDisabled={isDisabled} onClick={onClick}>
      <Icon as={FiArrowRight} boxSize={3.5} />
      <Text as="span" className="ide-move-file-label">Переместить</Text>
    </Button>
  </Tooltip>;
}
