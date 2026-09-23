import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Button, HStack, Icon, Progress, Text, Tooltip, VStack } from '@chakra-ui/react';
import { FiCloud, FiFileText, FiPlus, FiX } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';

function uploadIntentId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else bytes.forEach((_value, index) => { bytes[index] = Math.floor(Math.random() * 256); });
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

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

export function WorkFileUpload({
  disabled = false,
  busy = false,
  onUpload,
  onPartial,
  compact = false,
}) {
  const inputRef = useRef(null);
  const controllerRef = useRef(null);
  const resetTimerRef = useRef(null);
  const mountedRef = useRef(false);
  const [selected, setSelected] = useState(null);
  const [state, setState] = useState('idle');
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);

  // The model hook owns request lifetime. This visual control can legitimately
  // be replaced when an absent workspace becomes ready while its upload is
  // still returning; aborting from the old control would turn a committed
  // upload into a browser-side ERR_ABORTED result.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (resetTimerRef.current) window.clearTimeout(resetTimerRef.current);
    };
  }, []);

  const start = useCallback(async (candidate, intentId = uploadIntentId()) => {
    if (!candidate || disabled || busy) return;
    if (resetTimerRef.current) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    setSelected({ file: candidate, intentId });
    setProgress(0);
    setState('uploading');
    const result = await onUpload?.(candidate, {
      signal: controller.signal,
      uploadIntentId: intentId,
      onProgress: (value) => {
        if (mountedRef.current) setProgress(Number.isFinite(value) ? value : 0);
      },
    });
    if (!mountedRef.current) return;
    if (controller.signal.aborted || result?.cancelled) {
      setState('cancelled');
    } else if (result === true || result?.ok) {
      if (result?.outcome === 'library_saved') {
        setState('partial');
        onPartial?.(result);
      } else {
        setState(result?.outcome === 'kept' ? 'kept' : 'complete');
        setProgress(100);
        resetTimerRef.current = window.setTimeout(() => {
          if (!mountedRef.current) return;
          setSelected(null);
          setState('idle');
          setProgress(0);
          resetTimerRef.current = null;
        }, 1200);
      }
    } else {
      setState(result?.status === 409 ? 'conflict' : 'error');
    }
    if (controllerRef.current === controller) controllerRef.current = null;
  }, [busy, disabled, onPartial, onUpload]);

  const choose = useCallback((event) => {
    const candidate = event.target.files?.[0];
    event.target.value = '';
    if (candidate) start(candidate);
  }, [start]);

  const drop = useCallback((event) => {
    event.preventDefault();
    setDragging(false);
    if (disabled || busy || state === 'uploading') return;
    const candidate = event.dataTransfer.files?.[0];
    if (candidate) start(candidate);
  }, [busy, disabled, start, state]);

  const cancel = useCallback(() => controllerRef.current?.abort(), []);
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
      <input data-testid="work-upload-input" ref={inputRef} type="file" hidden onChange={choose} />
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
          aria-label="Добавить файл в библиотеку и рабочее место"
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
              <Text fontSize="11px" color={colors.fg[4]}>или нажмите, чтобы выбрать · агент не запускается</Text>
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
            {state === 'uploading' && (
              <Button size="xs" variant="ghost" leftIcon={<FiX />} onClick={cancel}>Отменить</Button>
            )}
            {['error', 'cancelled'].includes(state) && (
              <Button size="xs" variant="outline" onClick={() => start(selected.file, selected.intentId)}>
                Проверить и повторить
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
            {UPLOAD_STATUS[state] || ''}
          </Text>
          {state === 'cancelled' && <Text mt={1.5} fontSize="11px" color={colors.fg[4]}>Загрузка отменена; библиотека перечитана.</Text>}
          {state === 'error' && <Text mt={1.5} fontSize="11px" color={colors.error}>Статус не подтверждён. Безопасный повтор использует тот же upload intent.</Text>}
          {state === 'conflict' && <Text mt={1.5} fontSize="11px" color={colors.error}>Этот upload intent уже относится к другому содержимому. Выберите файл заново.</Text>}
          {state === 'partial' && <Text mt={1.5} fontSize="11px" color={colors.warning}>Источник сохранён в библиотеке. Рабочую копию можно добавить позже.</Text>}
          {state === 'kept' && <Text mt={1.5} fontSize="11px" color={colors.fg[4]}>Источник сохранён; существующая рабочая копия не перезаписана.</Text>}
        </Box>
      )}
    </VStack>
  );
}
