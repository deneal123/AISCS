import React from 'react';
import { Box, Button, Icon, Spinner } from '@chakra-ui/react';
import { borderRadius, colors, composerActionControl, motion } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';

const surface = '& [data-composer-action-surface]';

export function ComposerActionSurface({ children, ...props }) {
  return <Box as="span" data-composer-action-surface display="inline-flex" alignItems="center" justifyContent="center"
    pointerEvents="none" boxSize={composerActionControl.surface} flexShrink={0}
    borderRadius={borderRadius.control} boxShadow="none"
    transition={`background-color 160ms ${motion.easeOut}, border-color 160ms ${motion.easeOut}`}
    {...props}>{children}</Box>;
}

/** Компактная подложка внутри неизменной прозрачной области нажатия. */
export default function ComposerActionControl({
  icon, children, surfaceProps, surfaceHoverBg = CHAT_THEME.panelHover,
  isLoading, isDisabled, onClick, ...props
}) {
  return <Button
    variant="ghost" size="sm" boxSize={composerActionControl.target} minW={composerActionControl.target}
    flexShrink={0} p={0} bg="transparent" boxShadow="none" borderRadius={borderRadius.sm}
    color={CHAT_THEME.textTertiary}
    _hover={{ bg: 'transparent', color: CHAT_THEME.textPrimary, [surface]: { bg: surfaceHoverBg } }}
    _active={{ bg: 'transparent', [surface]: { bg: surfaceHoverBg } }}
    _focusVisible={{ outline: 'none', boxShadow: 'none', [surface]: { outline: `2px solid ${colors.border.focus}`, outlineOffset: '2px' } }}
    _disabled={{ opacity: 0.4, cursor: 'not-allowed' }}
    {...props}
    type="button" onClick={onClick}
    isDisabled={isDisabled || isLoading} aria-busy={isLoading || undefined}
  >
    <ComposerActionSurface bg="transparent" {...surfaceProps}>
      {isLoading ? <Spinner aria-hidden="true" label="" size="sm" />
        : children || <Icon aria-hidden="true" as={icon} boxSize={composerActionControl.glyph} />}
    </ComposerActionSurface>
  </Button>;
}
