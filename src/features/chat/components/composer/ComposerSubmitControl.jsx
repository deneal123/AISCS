import React from 'react';
import { Box } from '@chakra-ui/react';
import { FiSend } from '@shared/icons';
import { colors } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';
import ComposerActionControl from './ComposerActionControl';

/** A compact visible action inside a full-sized send/stop touch target. */
export default function ComposerSubmitControl({ streaming, canSend, uploading, onSend, onStop }) {
  const hover = streaming ? CHAT_THEME.panelHover : canSend ? CHAT_THEME.accentHover : 'transparent';
  return <ComposerActionControl
    aria-label={streaming ? 'Остановить генерацию' : 'Отправить'}
    title={streaming ? 'Остановить (Esc)' : uploading ? 'Дождитесь загрузки файла' : canSend ? 'Отправить (Enter)' : 'Введите сообщение'}
    color={streaming ? CHAT_THEME.textPrimary : canSend ? colors.fg[1] : CHAT_THEME.textSecondary}
    surfaceHoverBg={hover}
    isDisabled={!streaming && !canSend} onClick={streaming ? onStop : onSend}
    icon={FiSend}
    surfaceProps={{ 'data-composer-submit-surface': true,
      bg: streaming ? CHAT_THEME.panelActive : canSend ? CHAT_THEME.accent : 'transparent',
      border: streaming ? `1px solid ${CHAT_THEME.panelBorderStrong}` : 'none' }}
  >{streaming ? <Box boxSize="11px" bg="currentColor" borderRadius="3px" /> : null}</ComposerActionControl>;
}
