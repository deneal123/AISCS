import { useLayoutEffect, useRef } from 'react';
import { Button, Icon, Popover, PopoverBody, PopoverCloseButton, PopoverContent,
  PopoverHeader, PopoverTrigger, Portal, useDisclosure } from '@chakra-ui/react';
import { FiInfo } from '@shared/icons';
import { borderRadius, colors, layers } from '@theme/tokens';

/** Click/focus-owned help, outside the workbench's layout and clipping regions. */
export default function WorkbenchInfoPopover({ label, title, closeLabel = `Закрыть: ${title}`, children }) {
  const { isOpen, onOpen, onClose } = useDisclosure();
  const closeRef = useRef(null);
  useLayoutEffect(() => { if (isOpen) closeRef.current?.focus({ preventScroll: true }); }, [isOpen]);
  return <Popover placement="bottom-end" initialFocusRef={closeRef} isOpen={isOpen} onOpen={onOpen} onClose={onClose}>
    <PopoverTrigger><Button size="document" variant="ghost" minW="30px" px={1}
      aria-label={label} title={label} onClick={onOpen}><Icon as={FiInfo} boxSize={3.5} /></Button></PopoverTrigger>
    <Portal>{isOpen && <PopoverContent w="280px" maxW="calc(100vw - 24px)" maxH="min(360px, 70dvh)" overflowY="auto"
      motionProps={{ animate: false }} style={{ visibility: 'visible', opacity: 1, transform: 'none' }}
      bg={colors.bg.menu} borderColor={colors.border.strong} borderRadius={borderRadius.md} zIndex={layers.popover}>
      <PopoverHeader pr={12} fontSize="13px" fontWeight={600} border={0}>{title}</PopoverHeader>
      <PopoverCloseButton ref={closeRef} aria-label={closeLabel} />
      <PopoverBody pt={1} pb={3} fontSize="12px" color={colors.fg[2]}>{children}</PopoverBody>
    </PopoverContent>}</Portal>
  </Popover>;
}
