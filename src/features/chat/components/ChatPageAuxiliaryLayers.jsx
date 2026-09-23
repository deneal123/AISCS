import React, { lazy, Suspense, useEffect, useState } from 'react';
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerOverlay,
} from '@chakra-ui/react';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_CONTENT_BG, DRAWER_OVERLAY_PROPS } from '@theme/drawer';
import { CHAT_THEME } from '../constants/theme';
import ChatCommandPalette from './ChatCommandPalette';

const ChatMemoryDrawer = lazy(() => import('./drawers/ChatMemoryDrawer'));
const ChatGraphDrawer = lazy(() => import('./drawers/ChatGraphDrawer'));
const ChatSettingsDrawer = lazy(() => import('./drawers/ChatSettingsDrawer'));
const ProfileDrawer = lazy(() => import('@features/profile').then((module) => ({
  default: module.ProfileDrawer,
})));

function useHasOpened(isOpen) {
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (isOpen) setOpened(true);
  }, [isOpen]);
  return opened;
}

/**
 * Owns every portal/lazy layer around the chat surface. Keeping portals out of
 * ChatPageContainer makes that module a composition shell and gives drawers a
 * single lifecycle boundary: mount on first open, then preserve close motion.
 */
export default function ChatPageAuxiliaryLayers({
  sidebar,
  palette,
  auth,
  surface,
  memory,
  graph,
  settings,
  profile,
}) {
  const memoryOpened = useHasOpened(memory.disclosure.isOpen);
  const graphOpened = useHasOpened(graph.disclosure.isOpen);
  const settingsOpened = useHasOpened(settings.disclosure.isOpen);
  const profileOpened = useHasOpened(profile.disclosure.isOpen);

  return (
    <>
      <Drawer
        isOpen={sidebar.disclosure.isOpen}
        placement="left"
        onClose={sidebar.disclosure.onClose}
      >
        <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
        <DrawerContent
          bg={DRAWER_CONTENT_BG}
          borderRight={`1px solid ${CHAT_THEME.panelBorder}`}
          p={0}
        >
          <DrawerCloseButton
            aria-label="Закрыть меню"
            mt={2}
            zIndex={2}
            {...DRAWER_CLOSE_BUTTON_PROPS}
          />
          <DrawerBody p={0} h="full">
            {sidebar.render(false, true, true)}
          </DrawerBody>
        </DrawerContent>
      </Drawer>

      <ChatCommandPalette
        isOpen={palette.state.isOpen}
        onClose={palette.state.close}
        recentThreads={palette.recentThreads}
        models={palette.models}
        actions={palette.actions}
      />

      <auth.Component isOpen={auth.isOpen} onClose={auth.onClose} {...auth.modalData} />

      <AlertDialog
        isOpen={Boolean(surface.pending)}
        leastDestructiveRef={surface.cancelRef}
        onClose={surface.onCancel}
      >
        <AlertDialogOverlay>
          <AlertDialogContent
            bg={DRAWER_CONTENT_BG}
            border={`1px solid ${CHAT_THEME.panelBorder}`}
          >
            <AlertDialogHeader fontSize="15px">Есть несохранённые изменения</AlertDialogHeader>
            <AlertDialogBody color={CHAT_THEME.textSecondary}>
              Если продолжить, локальный черновик будет удалён. Сохраните или
              скопируйте изменения, если они ещё нужны.
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={surface.cancelRef} variant="ghost" onClick={surface.onCancel}>
                Продолжить редактирование
              </Button>
              <Button colorScheme="blue" ml={3} onClick={surface.onConfirm}>
                Отбросить и перейти
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>

      {memoryOpened && (
        <Suspense fallback={null}>
          <ChatMemoryDrawer
            isOpen={memory.disclosure.isOpen}
            onClose={memory.disclosure.onClose}
            memoryFacts={memory.facts}
            memoryDashboard={memory.dashboard}
            onSearch={memory.onSearch}
            onDeleteFact={memory.onDeleteFact}
            onAddFact={memory.onAddFact}
            onClearAll={memory.onClearAll}
          />
        </Suspense>
      )}

      {graphOpened && (
        <Suspense fallback={null}>
          <ChatGraphDrawer
            isOpen={graph.disclosure.isOpen}
            onClose={graph.disclosure.onClose}
            loadSummary={graph.loadSummary}
            onSearch={graph.onSearch}
            onDelete={graph.onDelete}
            onOpenHtml={graph.onOpenHtml}
          />
        </Suspense>
      )}

      {settingsOpened && (
        <Suspense fallback={null}>
          <ChatSettingsDrawer
            isOpen={settings.disclosure.isOpen}
            onClose={settings.disclosure.onClose}
            {...settings.props}
          />
        </Suspense>
      )}

      {profileOpened && (
        <Suspense fallback={null}>
          <ProfileDrawer
            isOpen={profile.disclosure.isOpen}
            onClose={profile.disclosure.onClose}
            {...profile.props}
          />
        </Suspense>
      )}
    </>
  );
}
