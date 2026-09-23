import { useRef, useState } from 'react';
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
} from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { WORK_SCROLLBAR_SX } from '../model/theme';
import { AgentActivityPanel } from './AgentActivityPanel';
import { DocumentForgePanel } from './DocumentForgePanel';
import { WorkHistoryPanel } from './WorkHistoryPanel';
import { WorkIssuesPanel } from './WorkIssuesPanel';

export function WorkContextPanel({
  room,
  history,
  file,
  busy,
  onCreateIssue,
  onUpdateIssue,
  onPreviewRevert,
  onControl,
  document,
}) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const cancelRef = useRef(null);

  const confirmStop = async () => {
    setConfirmCancel(false);
    await onControl('cancel');
  };

  return (
    <>
      <Tabs
        h="full"
        display="flex"
        flexDirection="column"
        variant="soft-rounded"
        colorScheme="blue"
      >
        <TabList px={2} py={2} flexShrink={0} aria-label="Контекст работы">
          <Tab fontSize="12px">Задачи</Tab>
          <Tab fontSize="12px">История</Tab>
          <Tab fontSize="12px">Агент</Tab>
          <Tab fontSize="12px">PDF</Tab>
        </TabList>
        <TabPanels flex="1" minH={0} overflow="hidden">
          <TabPanel h="full" overflow="auto" sx={WORK_SCROLLBAR_SX} px={3}>
            <WorkIssuesPanel
              room={room}
              file={file}
              busy={busy}
              onCreateIssue={onCreateIssue}
              onUpdateIssue={onUpdateIssue}
            />
          </TabPanel>
          <TabPanel h="full" overflow="auto" sx={WORK_SCROLLBAR_SX} px={3}>
            <WorkHistoryPanel
              history={history}
              busy={busy}
              onPreviewRevert={onPreviewRevert}
            />
          </TabPanel>
          <TabPanel h="full" overflow="auto" sx={WORK_SCROLLBAR_SX} px={3}>
            <AgentActivityPanel
              room={room}
              busy={busy}
              onControl={onControl}
              onRequestCancel={() => setConfirmCancel(true)}
            />
          </TabPanel>
          <TabPanel h="full" overflow="auto" sx={WORK_SCROLLBAR_SX} px={3}>
            <DocumentForgePanel document={document} />
          </TabPanel>
        </TabPanels>
      </Tabs>
      <AlertDialog
        isOpen={confirmCancel}
        leastDestructiveRef={cancelRef}
        onClose={() => setConfirmCancel(false)}
      >
        <AlertDialogOverlay>
          <AlertDialogContent
            bg={colors.bg.card}
            border={`1px solid ${colors.border.subtle}`}
          >
            <AlertDialogHeader fontSize="15px">Остановить агента?</AlertDialogHeader>
            <AlertDialogBody color={colors.fg[3]}>
              Текущая безопасная операция завершится или будет отменена существующим
              механизмом. Сохранённые файлы не удаляются.
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelRef} variant="ghost" onClick={() => setConfirmCancel(false)}>
                Не останавливать
              </Button>
              <Button ml={3} colorScheme="red" onClick={confirmStop}>
                Остановить
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  );
}
