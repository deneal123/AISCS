import { Box, Button, HStack, Text, VStack } from '@chakra-ui/react';
import { borderRadius, colors } from '@theme/tokens';
import { ACTIVITY_LABELS } from '../model/constants';

function formatDate(value) {
  const parsed = new Date(value ? value * 1000 : '');
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString('ru-RU');
}

export function AgentActivityPanel({ room, busy, onControl, onRequestCancel }) {
  const control = room?.control?.state || 'running';
  const paused = ['pause_requested', 'paused'].includes(control);

  return (
    <VStack align="stretch" spacing={3}>
      <Box
        p={3}
        borderRadius={borderRadius.md}
        bg={colors.accent.softest}
        border={`1px solid ${colors.accent.subtleBorder}`}
      >
        <Text fontSize="12.5px" color={colors.fg[2]} fontWeight="600">
          {paused
            ? 'Агент на паузе'
            : control === 'cancelled' ? 'Запуск отменён' : 'Агент может работать'}
        </Text>
        <Text mt={1} fontSize="11px" color={colors.fg[4]}>
          Пауза применяется между безопасными шагами и не прерывает активную операцию.
        </Text>
        <HStack mt={3}>
          {paused ? (
            <Button
              size="xs"
              colorScheme="green"
              onClick={() => onControl('resume')}
              isLoading={busy === 'control:resume'}
            >
              Продолжить
            </Button>
          ) : (
            <Button
              size="xs"
              variant="outline"
              onClick={() => onControl('pause')}
              isDisabled={control === 'cancelled'}
              isLoading={busy === 'control:pause'}
            >
              Пауза
            </Button>
          )}
          <Button
            size="xs"
            colorScheme="red"
            variant="ghost"
            onClick={onRequestCancel}
            isDisabled={control === 'cancelled'}
            isLoading={busy === 'control:cancel'}
          >
            Остановить
          </Button>
        </HStack>
      </Box>
      <Text fontSize="11px" color={colors.fg[4]} textTransform="uppercase">
        Активность агента
      </Text>
      {(room?.activity || []).map((item, index) => (
        <HStack
          key={`${item.at}-${item.kind}-${index}`}
          p={2.5}
          borderRadius={borderRadius.sm}
          bg={colors.border.faint}
        >
          <Text flex="1" fontSize="11.5px" color={colors.fg[3]}>
            {ACTIVITY_LABELS[item.kind] || 'Состояние рабочего места обновлено'}
          </Text>
          <Text fontSize="10px" color={colors.fg[4]}>{formatDate(item.at)}</Text>
        </HStack>
      ))}
    </VStack>
  );
}
