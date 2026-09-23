import { Box, Button, Text, VStack } from '@chakra-ui/react';
import { FiRotateCcw } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { HISTORY_TYPE_LABELS } from '../model/constants';

function formatDate(value) {
  const parsed = new Date(value ? value * 1000 : '');
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString('ru-RU');
}

export function WorkHistoryPanel({ history, busy, onPreviewRevert }) {
  return (
    <VStack align="stretch" spacing={2}>
      {history.length === 0 && (
        <Text fontSize="12px" color={colors.fg[4]}>Снимков пока нет.</Text>
      )}
      {history.map((item) => (
        <Box
          key={item.ref}
          p={3}
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.border.subtle}`}
        >
          <Text fontSize="12px" color={colors.fg[2]}>
            {HISTORY_TYPE_LABELS[item.message] || 'Снимок рабочего места'}
          </Text>
          <Text mt={1} fontSize="10px" color={colors.fg[4]}>
            {formatDate(item.at)} · {String(item.ref || '').slice(0, 8)}
          </Text>
          <Button
            mt={2}
            size="xs"
            leftIcon={<FiRotateCcw />}
            variant="ghost"
            onClick={() => onPreviewRevert(item.ref)}
            isLoading={busy === `diff:${item.ref}`}
          >
            Показать diff
          </Button>
        </Box>
      ))}
    </VStack>
  );
}
