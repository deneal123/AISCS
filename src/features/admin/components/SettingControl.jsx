import { useState } from 'react';
import {
  Box,
  Button,
  HStack,
  Input,
  NumberInput,
  NumberInputField,
  Switch,
  Text,
  VStack,
} from '@chakra-ui/react';
import AppTextarea from '@shared/controls/AppTextarea';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, INPUT_BASE } from '@theme/glass';
import { GHOST_BUTTON_BLUE_SX } from '@theme/styles';

// Контрол одной настройки: тип определяет виджет (bool/int/float/str/json).
export default function SettingControl({ spec, onSave, onReset }) {
  const isJson = spec.type === 'json';
  const [value, setValue] = useState(spec.value);
  const [jsonText, setJsonText] = useState(
    isJson ? JSON.stringify(spec.value, null, 2) : '',
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const save = async () => {
    setErr(null);
    let payload = value;
    if (isJson) {
      try {
        payload = JSON.parse(jsonText);
      } catch {
        setErr('Невалидный JSON');
        return;
      }
    }
    setBusy(true);
    try {
      await onSave(spec.key, payload);
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Ошибка сохранения');
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      await onReset(spec.key);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box p={3.5} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <HStack
        justify="space-between"
        align={{ base: 'stretch', sm: 'flex-start' }}
        flexDirection={{ base: 'column', sm: 'row' }}
        spacing={{ base: 3, sm: 4 }}
      >
        <VStack align="flex-start" spacing={0.5} flex="1" minW={0}>
          <HStack spacing={2} align="center" flexWrap="wrap">
            <Text fontSize="sm" color={CHAT_THEME.textPrimary} fontWeight="600">
              {spec.label}
            </Text>
            {spec.overridden && (
              <HStack
                spacing={1}
                px={1.5}
                py="1px"
                borderRadius="full"
                bg={colors.warningSoft}
                border={`1px solid ${colors.warningBorder}`}
              >
                <Box as="span" w="5px" h="5px" borderRadius="full" bg={colors.warning} />
                <Text fontSize="9px" fontWeight="600" color={colors.warning} textTransform="uppercase" letterSpacing="0.04em">
                  переопределено
                </Text>
              </HStack>
            )}
          </HStack>
          <Text fontSize="10.5px" color={CHAT_THEME.textTertiary} fontFamily="mono">
            {spec.key}
          </Text>
          {spec.description && (
            <Text fontSize="11.5px" color={CHAT_THEME.textSecondary} lineHeight="1.5" mt={0.5}>
              {spec.description}
            </Text>
          )}
        </VStack>

        <Box flexShrink={0} w={{ base: '100%', sm: 'auto' }}>
          {spec.type === 'bool' && (
            <Switch isChecked={Boolean(value)} onChange={(e) => setValue(e.target.checked)} />
          )}
          {(spec.type === 'int' || spec.type === 'float') && (
            <NumberInput
              size="sm"
              w={{ base: '100%', sm: '140px' }}
              value={value}
              min={spec.minimum ?? undefined}
              max={spec.maximum ?? undefined}
              onChange={(_, n) => setValue(Number.isNaN(n) ? 0 : n)}
            >
              <NumberInputField {...INPUT_BASE} />
            </NumberInput>
          )}
          {spec.type === 'str' && (
            <Input
              size="sm"
              w={{ base: '100%', sm: '220px' }}
              value={value ?? ''}
              onChange={(e) => setValue(e.target.value)}
              {...INPUT_BASE}
            />
          )}
        </Box>
      </HStack>

      {isJson && (
        <AppTextarea
          mt={2}
          fontFamily="mono"
          fontSize="12px"
          rows={5}
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
          resize="none"
          {...INPUT_BASE}
        />
      )}

      {err && (
        <Text mt={1} fontSize="11px" color={colors.error}>
          {err}
        </Text>
      )}

      <HStack mt={2.5} spacing={2} justify="flex-end" flexWrap="wrap">
        {spec.overridden && (
          <Button size="xs" variant="ghost" color={CHAT_THEME.textSecondary} onClick={reset} isDisabled={busy}>
            Сбросить
          </Button>
        )}
        <Button size="xs" {...GHOST_BUTTON_BLUE_SX} onClick={save} isLoading={busy}>
          Сохранить
        </Button>
      </HStack>
    </Box>
  );
}
