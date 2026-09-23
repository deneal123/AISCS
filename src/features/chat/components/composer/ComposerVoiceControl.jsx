import React from 'react';
import { Box, HStack, Icon, IconButton, Spinner, Text, keyframes } from '@chakra-ui/react';
import { FiMic, FiSquare } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';

// Пульсирующее кольцо вокруг активной записи — явный сигнал «идёт запись».
const pulseRing = keyframes`
  0% { box-shadow: 0 0 0 0 rgba(45, 91, 255, 0.40); }
  70% { box-shadow: 0 0 0 6px rgba(45, 91, 255, 0); }
  100% { box-shadow: 0 0 0 0 rgba(45, 91, 255, 0); }
`;
const blink = keyframes`50% { opacity: 0.35; }`;

function formatElapsed(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function ComposerVoiceControl({ recordingState, isTranscribing, elapsedSec = 0, onToggle }) {
  const isRecording = recordingState === 'recording';

  // Распознавание после остановки — спиннер, отправка заблокирована выше.
  if (isTranscribing) {
    return (
      <HStack spacing={2} px={3} h="32px" borderRadius={borderRadius.full} bg={CHAT_THEME.panelHover}>
        <Spinner size="xs" color={colors.iris[300]} speed="0.7s" />
        <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Распознаю…</Text>
      </HStack>
    );
  }

  // Активная запись — пульсирующая пилюля с таймером и стоп-иконкой (клик = стоп).
  if (isRecording) {
    return (
      <HStack
        as="button"
        type="button"
        onClick={onToggle}
        aria-label="Остановить запись"
        spacing={2}
        px={3}
        h="32px"
        borderRadius={borderRadius.full}
        bg={CHAT_THEME.accentSoft}
        border="1px solid"
        borderColor={colors.accent.glow}
        sx={{
          animation: `${pulseRing} 1.6s ease-out infinite`,
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
        _hover={{ bg: CHAT_THEME.panelHover }}
      >
        <Box
          w="8px"
          h="8px"
          borderRadius="full"
          bg={colors.brand.primary}
          sx={{
            animation: `${blink} 1s steps(1, end) infinite`,
            '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
          }}
        />
        <Text fontSize="12px" fontWeight="600" fontFamily="mono" color={CHAT_THEME.accent}>
          {formatElapsed(elapsedSec)}
        </Text>
        <Icon as={FiSquare} boxSize="11px" color={CHAT_THEME.accent} />
      </HStack>
    );
  }

  return (
    <IconButton
      aria-label="Голосовой ввод"
      icon={<FiMic />}
      size="sm"
      variant="ghost"
      color={CHAT_THEME.textTertiary}
      _hover={{ color: CHAT_THEME.textPrimary, bg: CHAT_THEME.panelHover }}
      borderRadius={borderRadius.sm}
      onClick={onToggle}
    />
  );
}

export default ComposerVoiceControl;
