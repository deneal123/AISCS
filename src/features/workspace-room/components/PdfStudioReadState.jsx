import { Button, Flex, Text } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';

/** Unknown and failed reads never advertise creation as a recovery action. */
export function PdfStudioReadState({ loading, label, onRetry, retryLabel = 'Повторить загрузку' }) {
  if (loading) return <AppLoading label={label} />;
  return <Flex flex="1" minH={0} direction="column" align="center" justify="center" p={5} gap={3}>
    <Text role="alert" color={colors.fg[3]} textAlign="center">{label}</Text>
    {onRetry && <Button size="workbench" variant="workbenchSecondary" onClick={onRetry}>{retryLabel}</Button>}
  </Flex>;
}
