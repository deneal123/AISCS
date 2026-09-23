import { Box, Button, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiFolder, FiPlus } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { workspaceStatusText } from '../model/constants';
import { WORK_HUB_THEME } from '../model/theme';

export function WorkLanding({ state, hasThread, busy, loading, onActivate, onRetry, uploadControl }) {
  const initialLoading = loading && state === 'absent';
  const canActivate = !initialLoading && hasThread && ['absent', 'expired'].includes(state);
  const title = initialLoading
    ? 'Загружаю рабочее состояние…'
    : !hasThread
    ? 'Выберите чат для рабочей среды'
    : state === 'absent'
      ? 'Рабочее место ещё не создано'
      : state === 'expired' ? 'Срок рабочей среды истёк' : 'Рабочее место временно недоступно';
  const description = initialLoading
    ? 'Библиотека и рабочее место появятся независимо, как только их данные будут готовы.'
    : !hasThread
    ? 'Постоянная библиотека доступна уже сейчас. Рабочая среда появляется только после явного действия в выбранном чате.'
    : state === 'absent'
      ? 'Создание среды и загрузка файла — явные действия. Открытие вкладки ничего не запускает.'
      : state === 'expired'
        ? 'Временные файлы больше недоступны. Библиотека сохранена, новую среду можно создать явно.'
        : (workspaceStatusText[state] || workspaceStatusText.unavailable);

  return (
    <Box h="full" overflow="auto" px={{ base: 4, md: 7 }} py={{ base: 5, md: 7 }}>
      <VStack align="stretch" spacing={4} maxW="620px" mx="auto">
        <Box
          role={initialLoading ? 'status' : undefined}
          p={{ base: 4, md: 5 }}
          borderRadius={borderRadius.lg}
          bg={WORK_HUB_THEME.panelBg}
          border={`1px solid ${colors.border.subtle}`}
        >
          <HStack align="start" spacing={3}>
            <Box boxSize="40px" flexShrink={0} borderRadius={borderRadius.md} bg={colors.accent.soft} display="grid" placeItems="center">
              <Icon as={FiFolder} boxSize="19px" color={colors.blue[300]} />
            </Box>
            <Box minW={0}>
              <Text fontSize="16px" fontWeight="650" color={colors.fg[1]}>{title}</Text>
              <Text mt={1} fontSize="12.5px" lineHeight="1.6" color={colors.fg[3]}>{description}</Text>
              <HStack mt={4} wrap="wrap">
                {canActivate && (
                  <Button data-testid="work-activate" leftIcon={<FiPlus />} size="sm" colorScheme="blue" onClick={onActivate} isLoading={busy === 'activate'}>
                    Создать среду
                  </Button>
                )}
                {state === 'unavailable' && (
                  <Button size="sm" variant="outline" onClick={onRetry} isLoading={loading}>
                    Повторить проверку
                  </Button>
                )}
              </HStack>
            </Box>
          </HStack>
        </Box>
        {hasThread && uploadControl}
      </VStack>
    </Box>
  );
}
