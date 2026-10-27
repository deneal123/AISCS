import { Drawer, DrawerBody, DrawerCloseButton, DrawerContent, DrawerHeader, DrawerOverlay } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_CONTENT_BG, DRAWER_OVERLAY_PROPS } from '@theme/drawer';

/** The lazy Work bundle must not hide Library's feedback behind the Chat surface. */
export default function ChatWorkLoading({ libraryOpen, onLibraryClose, libraryReturnFocus }) {
  return <>
    <AppLoading label="Загружаю рабочее место…" />
    <Drawer isOpen={Boolean(libraryOpen)} onClose={onLibraryClose} placement="right" size="md" finalFocusRef={libraryReturnFocus}>
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
      <DrawerContent bg={DRAWER_CONTENT_BG} data-testid="workbench-library-pending">
        <DrawerCloseButton aria-label="Закрыть библиотеку" {...DRAWER_CLOSE_BUTTON_PROPS} />
        <DrawerHeader>Библиотека</DrawerHeader>
        <DrawerBody display="flex"><AppLoading label="Загружаю библиотеку…" /></DrawerBody>
      </DrawerContent>
    </Drawer>
  </>;
}
