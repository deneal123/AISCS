import React, { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react';
import {
  Box, Button, Drawer, DrawerBody, DrawerCloseButton, DrawerContent, DrawerFooter,
  DrawerHeader, DrawerOverlay, HStack, Icon, Popover, PopoverBody, PopoverCloseButton,
  PopoverContent, PopoverHeader, PopoverTrigger, Portal, Text,
} from '@chakra-ui/react';
import { FiChevronDown } from '@shared/icons';
import { useResponsive } from '@hooks/useResponsive';
import { borderRadius, colors, layers, shadows } from '@theme/tokens';
import { DRAWER_OVERLAY_PROPS } from '@theme/drawer';
import { ChoiceHints } from './ChoiceHint';
import useChoicePanelGeometry from './choice-panel/useChoicePanelGeometry';

const ChoiceContext = createContext(null);
// Панели быстрого выбора не задерживают активацию/закрытие анимацией оболочки.
const IMMEDIATE_CHOICE_MOTION = {
  initial: false,
  animate: { opacity: 1, transition: { duration: 0 } },
  exit: { opacity: 0, transition: { duration: 0 } },
};

export function ChoicePanelGroup({ children, onOpenChange, compact = false, enabled = true }) {
  const [active, setActive] = useState(null);
  useEffect(() => { if (!enabled) setActive(null); }, [enabled]);
  useEffect(() => { onOpenChange?.(active !== null); }, [active, onOpenChange]);
  return <ChoiceContext.Provider value={{ active, setActive, compact }}>{children}</ChoiceContext.Provider>;
}

/** Library-owned focus/keyboard semantics; one responsive surface, no independent menu stack. */
export default function ChoicePanel({ label, compactLabel, title, compactTitle, icon, iconColor, triggerTestId, mobileIcon, mobileIconOnly = false, selected = false, width = 320, compactWidth, compactListHeight = 224, headerAction, placement = 'top-start', children, done = false, variant = 'default', mobileWidth }) {
  const id = useId();
  const group = useContext(ChoiceContext);
  const [localActive, setLocalActive] = useState(null);
  const active = group ? group.active : localActive;
  const setActive = group ? group.setActive : setLocalActive;
  const open = active?.id === id;
  const ticket = active?.ticket;
  const close = () => setActive((previous) => previous?.id === id && previous.ticket === ticket ? null : previous);
  const triggerRef = useRef(null);
  const closeRef = useRef(null);
  const latestActive = useRef(active);
  latestActive.current = active;
  const wasOpen = useRef(false);
  const parentDialogRef = useRef(null);
  parentDialogRef.current = triggerRef.current?.closest('[role="dialog"]') || null;
  const { isMobile } = useResponsive();
  const compact = isMobile || group?.compact;
  const triggerIcon = compact && mobileIconOnly ? (mobileIcon || icon) : icon;
  const iconOnly = compact && mobileIconOnly && !!triggerIcon;
  const singleChoicePalette = variant === 'mode-palette' || variant === 'model-palette' || variant === 'status-palette';
  const contentPalette = singleChoicePalette || variant === 'persona-palette';
  const emphasized = selected || open;
  const { viewportHeight, viewportBottomInset, gutter, panelHeight } = useChoicePanelGeometry(open, triggerRef);
  const restoreFocus = useCallback(() => {
    // An older exit must not steal focus from a reopened or different picker.
    if (latestActive.current === null) triggerRef.current?.focus({ preventScroll: true });
  }, []);
  useEffect(() => {
    if (wasOpen.current && !open && !isMobile) restoreFocus();
    wasOpen.current = open;
  }, [open, isMobile, restoreFocus]);

  const trigger = (
    <Button ref={triggerRef} data-testid={triggerTestId} aria-label={label} title={label} aria-expanded={open} aria-haspopup="dialog"
      h={iconOnly ? '44px' : { base: '44px', md: '34px' }} w={iconOnly ? '44px' : undefined}
      minW={iconOnly ? '44px' : 0} maxW="100%" px={iconOnly ? 0 : 3} size="sm"
      borderRadius={borderRadius.full} fontSize="12px" fontWeight={600}
      color={emphasized ? colors.blue[100] : colors.fg[2]}
      bg={iconOnly ? 'transparent' : emphasized ? colors.accent.subtle : colors.bg.input}
      border={iconOnly ? 0 : '1px solid'} borderColor={emphasized ? colors.accent.subtleBorder : colors.border.medium}
      _hover={iconOnly ? { bg: 'transparent', '& [data-choice-glyph]': { bg: colors.surface.tint3, borderColor: colors.border.strong } }
        : { bg: colors.surface.tint3, borderColor: colors.border.strong }}
      _active={iconOnly ? { bg: 'transparent', '& [data-choice-glyph]': { bg: colors.glass.active } } : { bg: colors.glass.active }}
      _focusVisible={iconOnly ? { outline: 'none', boxShadow: 'none', '& [data-choice-glyph]': { outline: `2px solid ${colors.border.focus}`, outlineOffset: '2px' } }
        : { outline: `2px solid ${colors.border.focus}`, outlineOffset: '2px' }}
      onClick={isMobile ? () => setActive((previous) => previous?.id === id ? null : { id, ticket: Symbol('choice') }) : undefined}>
      {iconOnly ? <Box as="span" data-choice-glyph aria-hidden="true" boxSize="30px" flexShrink={0}
        display="inline-flex" alignItems="center" justifyContent="center" borderRadius={borderRadius.full}
        bg={emphasized ? colors.accent.subtle : colors.bg.input} border="1px solid"
        borderColor={emphasized ? colors.accent.subtleBorder : colors.border.medium}>
        <Icon as={triggerIcon} boxSize={4} color={iconColor} />
      </Box> : <HStack spacing={1.5} minW={0}>
          {triggerIcon && <Icon as={triggerIcon} boxSize={3.5} flexShrink={0} />}
          <Text as="span" noOfLines={1} minW={0}>{isMobile && compactLabel ? compactLabel : label}</Text>
          <Icon as={FiChevronDown} boxSize={3} flexShrink={0} />
      </HStack>}
    </Button>
  );
  const body = children({ close, isMobile, compact: iconOnly, inputId: `choice-${id.replace(/:/g, '')}` });
  const geometry = { '--choice-list-height': `${Math.max(64, Math.min(iconOnly ? compactListHeight : 320, viewportHeight * 0.8 - 230))}px` };

  return (
    <>
    <Popover isOpen={!isMobile && open} onOpen={() => { if (!isMobile) setActive({ id, ticket: Symbol('choice') }); }} onClose={close}
      placement={placement} returnFocusOnClose={false} closeOnBlur gutter={gutter}>
      {isMobile ? trigger : <PopoverTrigger>{trigger}</PopoverTrigger>}
      <Portal containerRef={parentDialogRef.current ? parentDialogRef : undefined}>
        {/* Mount only the open surface: touch WebKit can retain a hidden
            ancestor's visibility on select inputs and option glyphs. */}
        {!isMobile && open && <PopoverContent w={`${iconOnly && compactWidth ? compactWidth : width}px`} maxW="calc(100vw - 24px)" maxH={`${panelHeight}px`}
          motionProps={{ animate: false }}
          style={{ visibility: 'visible', opacity: 1, transform: 'none' }}
          bg={colors.bg.menu} borderColor={colors.border.strong} borderRadius={borderRadius.md}
          boxShadow={shadows.menu} zIndex={layers.popover} sx={geometry} overflow="hidden">
          <PopoverHeader border={0} fontSize={iconOnly ? '13px' : '14px'} fontWeight={600} pl={3} py={2} pr={10} display="flex" alignItems="center" justifyContent="space-between">{iconOnly && compactTitle ? compactTitle : title}{iconOnly && headerAction}</PopoverHeader>
          <PopoverCloseButton aria-label={`Закрыть: ${title}`} boxSize="32px" />
          <PopoverBody pt={0} px={2} pb={2} overflowY="auto"><ChoiceHints>{!isMobile && open && body}</ChoiceHints></PopoverBody>
          {done && <Box px={2} pb={2}><Button variant="secondary" size="document" w="100%" onClick={close}>Готово</Button></Box>}
        </PopoverContent>}
      </Portal>
    </Popover>
    <Drawer isOpen={isMobile && open} onClose={close} placement="bottom" initialFocusRef={closeRef}
      motionPreset={contentPalette ? 'none' : undefined}
      finalFocusRef={triggerRef} returnFocusOnClose={isMobile} trapFocus={isMobile}>
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} zIndex={layers.backdrop} />
      <DrawerContent motionProps={contentPalette ? IMMEDIATE_CHOICE_MOTION : undefined}
        zIndex={layers.drawer} maxH={`${viewportHeight * 0.8}px`} bg={colors.ink[900]}
        w={contentPalette ? `${mobileWidth || 280}px` : undefined}
        mx={contentPalette ? 'auto' : undefined}
        // Slide sets maxWidth inline; keep the palette's viewport bound in that layer.
        style={{ bottom: viewportBottomInset, ...(contentPalette ? { maxWidth: 'calc(100vw - 24px)', transform: 'none' } : {}) }}
        borderTopRadius={borderRadius.lg} borderTop="1px solid" borderColor={colors.border.strong} sx={geometry}>
        <Box display="flex" alignItems="center" pr={14}>
          <DrawerHeader flex="1" minW={0} pr={0} fontSize="15px">{title}</DrawerHeader>
          {iconOnly && headerAction}
        </Box>
        <DrawerCloseButton ref={closeRef} aria-label={`Закрыть: ${title}`} boxSize="44px" />
        <DrawerBody px={3} pt={0} pb={3} minH={0}><ChoiceHints>{isMobile && open && body}</ChoiceHints></DrawerBody>
        {(!singleChoicePalette || done) && <DrawerFooter data-toast-protected-actions borderTop="1px solid" borderColor={colors.border.subtle} pt={3} pb="calc(12px + env(safe-area-inset-bottom))">
          <Button variant="secondary" onClick={close} w="100%" h="44px" fontSize="13px"
            color={done ? colors.blue[100] : colors.fg[2]}
            bg={done ? colors.accent.subtle : undefined}
            borderColor={done ? colors.accent.subtleBorder : colors.border.medium}>{done ? 'Готово' : 'Закрыть'}</Button>
        </DrawerFooter>}
      </DrawerContent>
    </Drawer>
    </>
  );
}
