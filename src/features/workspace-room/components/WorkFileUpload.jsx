import { useCallback, useRef, useState } from 'react';
import { Box, Button, HStack, Icon, Progress, Text, Tooltip, VStack } from '@chakra-ui/react';
import { FiCloud, FiFileText, FiPlus, FiX } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { useWorkUploadSelection } from '../model/useWorkUploadSelection';

function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

const UPLOAD_STATUS = {
  uploading: 'Загрузка выполняется',
  cancelled: 'Загрузка отменена',
  error: 'Статус загрузки не подтверждён',
  conflict: 'Файл не соответствует предыдущей попытке',
  partial: 'Источник сохранён только в библиотеке',
  kept: 'Существующая рабочая копия сохранена',
  complete: 'Файл добавлен',
};

export function WorkFileUpload(props) {
  if (props.session) return <WorkFileUploadView {...props} />;
  return <StandaloneWorkFileUpload {...props} />;
}

function StandaloneWorkFileUpload(props) {
  const session = useWorkUploadSelection(props);
  return <WorkFileUploadView {...props} session={session} />;
}

function WorkFileUploadView({
  disabled = false,
  busy = false,
  session,
  compact = false,
  libraryOnly = false,
}) {
  const inputRef = useRef(null);
  const { selected, state, progress, start, cancel } = session;
  const [dragging, setDragging] = useState(false);

  const choose = useCallback((event) => {
    const candidate = event.target.files?.[0];
    event.target.value = '';
    if (candidate && !disabled && !busy && state !== 'uploading') start(candidate);
  }, [busy, disabled, start, state]);

  const drop = useCallback((event) => {
    event.preventDefault();
    setDragging(false);
    if (disabled || busy || state === 'uploading') return;
    const candidate = event.dataTransfer.files?.[0];
    if (candidate) start(candidate);
  }, [busy, disabled, start, state]);

  const label = compact ? 'Добавить файл' : 'Выбрать файл';
  const control = (
    <Button
      size="sm"
      leftIcon={<FiPlus />}
      colorScheme="blue"
      onClick={() => inputRef.current?.click()}
      isDisabled={disabled || busy || state === 'uploading'}
      isLoading={state === 'uploading'}
    >
      {label}
    </Button>
  );

  return (
    <VStack align="stretch" spacing={2} minW={0} w={compact ? 'auto' : 'full'}>
      <input data-testid="work-upload-input" ref={inputRef} type="file" hidden
        disabled={disabled || busy || state === 'uploading'} onChange={choose} />
      {compact ? (
        disabled
          ? <Tooltip label="Выберите чат, чтобы добавить файл в его рабочее место">{control}</Tooltip>
          : control
      ) : (
        <Box
          as="button"
          type="button"
          disabled={disabled || busy || state === 'uploading'}
          aria-disabled={disabled || busy || state === 'uploading'}
          aria-label={libraryOnly ? 'Добавить файл в библиотеку' : 'Добавить файл в библиотеку и рабочее место'}
          onClick={() => !disabled && inputRef.current?.click()}
          onDragEnter={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
          w="full"
          px={4}
          py={4}
          textAlign="left"
          cursor={disabled ? 'not-allowed' : 'pointer'}
          borderRadius={borderRadius.lg}
          border={`1px dashed ${dragging ? colors.border.focus : colors.accent.subtleBorder}`}
          bg={dragging ? colors.accent.hoverSoft : colors.accent.softest}
          _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '2px' }}
        >
          <HStack spacing={3} pointerEvents="none">
            <Box boxSize="34px" borderRadius={borderRadius.md} bg={colors.accent.soft} display="grid" placeItems="center">
              <Icon as={FiCloud} color={colors.blue[300]} />
            </Box>
            <Box minW={0}>
              <Text fontSize="12.5px" fontWeight="600" color={colors.fg[2]}>Перетащите файл сюда</Text>
              <Text fontSize="11px" color={colors.fg[3]}>или нажмите, чтобы выбрать · агент не запускается</Text>
            </Box>
          </HStack>
        </Box>
      )}
      {selected && (
        <Box
          w="full"
          px={3}
          py={2.5}
          borderRadius={borderRadius.md}
          bg={colors.bg.card}
          border={`1px solid ${['error', 'conflict'].includes(state) ? colors.error : colors.border.subtle}`}
        >
          <HStack spacing={2} minW={0}>
            <FiFileText color={colors.blue[300]} />
            <Text flex="1" minW={0} noOfLines={1} fontSize="12px" color={colors.fg[2]}>
              {selected.file.name}
            </Text>
            <Text flexShrink={0} fontSize="10px" color={colors.fg[4]}>
              {formatFileSize(selected.file.size)}
            </Text>
            {['uploading', 'error', 'cancelled'].includes(state) && (
              <Button size="xs" variant={state === 'uploading' ? 'ghost' : 'outline'}
                leftIcon={state === 'uploading' ? <FiX /> : undefined}
                isDisabled={state !== 'uploading' && (disabled || busy)}
                onClick={() => {
                  if (state === 'uploading') cancel();
                  else if (!disabled && !busy) start(selected.file, selected.intentId, selected.options);
                }}>
                {state === 'uploading' ? 'Отменить' : 'Проверить и повторить'}
              </Button>
            )}
          </HStack>
          {state === 'uploading' && (
            <Progress
              mt={2}
              value={progress}
              isIndeterminate={!progress}
              size="xs"
              colorScheme="blue"
              borderRadius="full"
            />
          )}
          <Text mt={1.5} fontSize="11px" color={colors.fg[4]} role="status" aria-live="polite">
            {state === 'complete' && selected.options?.libraryOnly ? 'Файл сохранён в библиотеке' : UPLOAD_STATUS[state] || ''}
          </Text>
          {state === 'cancelled' && <Text mt={1.5} fontSize="11px" color={colors.fg[4]}>Загрузка отменена. Проверьте библиотеку перед повтором.</Text>}
          {state === 'error' && <Text mt={1.5} fontSize="11px" color={colors.error}>Статус не подтверждён. Проверьте библиотеку перед повтором. Повтор относится к той же загрузке.</Text>}
          {state === 'conflict' && <Text mt={1.5} fontSize="11px" color={colors.error}>Содержимое файла отличается от предыдущей попытки. Выберите файл заново.</Text>}
          {state === 'partial' && <Text mt={1.5} fontSize="11px" color={colors.warning}>Источник сохранён в библиотеке. Рабочую копию можно добавить позже.</Text>}
          {state === 'kept' && <Text mt={1.5} fontSize="11px" color={colors.fg[4]}>Источник сохранён; существующая рабочая копия не перезаписана.</Text>}
        </Box>
      )}
    </VStack>
  );
}
