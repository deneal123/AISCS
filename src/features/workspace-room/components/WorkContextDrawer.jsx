import {
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
} from '@chakra-ui/react';
import { colors } from '@theme/tokens';

export function WorkContextDrawer({ isOpen, onClose, finalFocusRef, children }) {
  return (
    <Drawer
      isOpen={isOpen}
      placement="right"
      size="sm"
      onClose={onClose}
      finalFocusRef={finalFocusRef}
    >
      <DrawerOverlay />
      <DrawerContent
        aria-labelledby="work-context-title"
        bg={colors.bg.card}
        borderLeft={`1px solid ${colors.border.subtle}`}
      >
        <DrawerCloseButton aria-label="Закрыть контекст" />
        <DrawerHeader
          as="h2"
          id="work-context-title"
          fontSize="15px"
          borderBottom={`1px solid ${colors.border.subtle}`}
        >
          Контекст
        </DrawerHeader>
        <DrawerBody p={0} minH={0}>{children}</DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
