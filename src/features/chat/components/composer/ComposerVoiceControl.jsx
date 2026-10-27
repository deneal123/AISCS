import React, { useId } from 'react';
import { Box, Icon, Spinner, Text, VStack, keyframes } from '@chakra-ui/react';
import { FiMic, FiSquare } from '@shared/icons';
import { colors, composerActionControl } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';
import ComposerActionControl, { ComposerActionSurface } from './ComposerActionControl';

// Пульсирующее кольцо вокруг активной записи — явный сигнал «идёт запись».
const pulseRing = keyframes`
  0% { box-shadow: 0 0 0 0 ${colors.accent.glow}; }
  70%, 100% { box-shadow: 0 0 0 6px transparent; }
`;

function formatElapsed(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function ComposerVoiceControl({ recordingState, isTranscribing, elapsedSec = 0, onToggle }) {
  const isRecording = recordingState === 'recording';
  const timerId = useId();

  // Распознавание после остановки — спиннер, отправка заблокирована выше.
  if (isTranscribing || recordingState === 'requesting') {
    const label = isTranscribing ? 'Распознаю голос…' : 'Ожидаю разрешения микрофона…';
    return (
      <Box role="status" aria-label={label} title={label}
        boxSize={composerActionControl.target} minW={composerActionControl.target} flexShrink={0}
        display="flex" alignItems="center" justifyContent="center">
        <ComposerActionSurface bg={CHAT_THEME.panelHover}>
          <Spinner aria-hidden="true" label="" size="sm" color={colors.iris[300]} speed="0.7s" />
        </ComposerActionSurface>
      </Box>
    );
  }

  // All states own the same slot; the timer cannot push controls into typed text.
  if (isRecording) {
    return (
      <ComposerActionControl
        onClick={onToggle}
        aria-label="Остановить запись"
        aria-describedby={timerId}
        title={`Остановить запись · ${formatElapsed(elapsedSec)}`}
        surfaceProps={{ bg: CHAT_THEME.accentSoft, border: `1px solid ${colors.accent.glow}`,
          sx: { animation: `${pulseRing} 1.6s ease-out infinite`,
            '@media (prefers-reduced-motion: reduce)': { animation: 'none' } },
        }}
      >
        <VStack as="span" spacing={0.5} maxW="100%" color={CHAT_THEME.accent}>
          <Icon as={FiSquare} boxSize="11px" />
          <Text as="span" id={timerId} role="timer" aria-live="off"
            fontSize="12px" fontWeight={600} fontFamily="mono" color={CHAT_THEME.textPrimary} lineHeight="1" whiteSpace="nowrap" flexShrink={0}>
            {formatElapsed(elapsedSec)}
          </Text>
        </VStack>
      </ComposerActionControl>
    );
  }

  return (
    <ComposerActionControl
      aria-label="Голосовой ввод"
      icon={FiMic}
      onClick={onToggle}
    />
  );
}

export default ComposerVoiceControl;
