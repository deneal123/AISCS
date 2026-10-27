import { useEffect, useRef, useState } from 'react';
import { Box, Drawer, DrawerBody, DrawerCloseButton, DrawerContent, DrawerHeader,
  DrawerOverlay, HStack, IconButton, Input, InputGroup, InputRightElement, Text, VStack } from '@chakra-ui/react';
import { FiRefreshCw, FiX } from '@shared/icons';
import AppSelect from '@shared/controls/AppSelect';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_CONTENT_BG, DRAWER_OVERLAY_PROPS } from '@theme/drawer';
import { colors } from '@theme/tokens';
import { isPdfImageName } from '../model/documentAssets';
import { WorkLibraryPane } from './WorkLibraryPane';
import { WorkFileUpload } from './WorkFileUpload';
import { useIdeLibraryCopy } from '../model/useIdeLibraryCopy';
import IdeLibraryDestination from './IdeLibraryDestination';
import { useLibraryBrowser } from '../model/useLibraryBrowser';

/** One account Library; Workspace/PDF are explicit copy destinations, not libraries. */
export function WorkbenchLibraryDrawer({ work, uploadSession, isOpen, onClose, finalFocusRef, blocked, ideTarget, preferIde = false }) {
  const closeRef = useRef(null);
  const [destination, setDestination] = useState('workspace');
  const searchRef = useRef(null);
  const browser = useLibraryBrowser({ enabled: isOpen && !work.hub.loading,
    revision: JSON.stringify(work.hub.library) });
  const project = work.document.project;
  const hasThread = Boolean(work.threadId) && work.hub.workspace.state !== 'unselected';
  const ideKey = ideTarget?.repository_id && ideTarget?.generation ? `ide:${ideTarget.repository_id}:${ideTarget.generation}` : '';
  const ideSelected = destination.startsWith('ide:');
  const projectTarget = !ideSelected && destination !== 'workspace';
  const targetValid = destination === 'workspace' || destination === project?.path || (ideKey && destination === ideKey);
  const ideCopy = useIdeLibraryCopy({ threadId: work.threadId, target: ideTarget, active: Boolean(isOpen && ideSelected && targetValid) });
  useEffect(() => { if (isOpen) setDestination(preferIde ? ideKey || 'ide:pending' : 'workspace'); }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (isOpen && destination === 'ide:pending' && ideKey) setDestination(ideKey); }, [destination, ideKey, isOpen]);
  const copying = Boolean(work.busy || ideCopy.busy);
  const copyBlocked = Boolean(blocked || !targetValid || (ideSelected && ideTarget?.blocked));
  const options = [{ value: 'workspace', label: 'Рабочее место этого чата' },
    ...(project ? [{ value: project.path, label: `PDF: ${work.document.authoring?.value?.draft?.title || project.title || project.profile?.label || 'Текущий проект'}` }] : []),
    ...(ideKey ? [{ value: ideKey, label: `IDE: ${ideTarget.name || 'Репозиторий'}` }] : [])];
  const copyAction = (item) => {
    if (ideSelected) return { label: 'В IDE…', ariaLabel: `Добавить ${item.name} в IDE`, disabled: copyBlocked,
      outcome: ideCopy.outcomes[item.file_id], feedback: ideCopy.outcomes[item.file_id] ? 'Копия добавлена в выбранный репозиторий.' : undefined,
      onCopy: (_file, sourceControl) => ideCopy.choose(item, sourceControl) };
    if (!projectTarget) return null;
    const compatible = isPdfImageName(item.name);
    const outcome = work.libraryOutcomes?.[`${destination}/${item.file_id}`];
    const feedback = { imported: 'Файл в проекте. Выберите его в блоке изображения.',
      kept: 'Файл уже в проекте; он не перезаписан.', conflict: 'Проект изменился. Обновите данные перед повторной попыткой.',
      busy: 'Проект занят. Повторите после завершения обработки.', unavailable: 'Копирование не подтверждено. Обновите данные.' }[outcome];
    return { label: 'В PDF-проект', ariaLabel: `Добавить ${item.name} в PDF-проект`,
      disabled: !compatible || !targetValid, outcome,
      feedback: compatible ? feedback : 'Для иллюстрации в PDF подходят PNG, JPEG и PDF. Другие материалы можно добавить в рабочее место.',
      onCopy: () => work.copyFromLibrary(item, { documentPath: destination }) };
  };
  return <Drawer isOpen={isOpen} onClose={() => { if (!ideCopy.busy) onClose(); }} placement="right" size="md" closeOnEsc={!ideCopy.busy}
    initialFocusRef={closeRef} finalFocusRef={finalFocusRef}>
    <DrawerOverlay {...DRAWER_OVERLAY_PROPS} />
    <DrawerContent bg={DRAWER_CONTENT_BG} data-testid="workbench-library">
      <DrawerCloseButton ref={closeRef} aria-label="Закрыть библиотеку" isDisabled={ideCopy.busy} {...DRAWER_CLOSE_BUTTON_PROPS} />
      <DrawerHeader>Библиотека</DrawerHeader>
      <DrawerBody display="flex" minH={0} flexDirection="column" pb={4}>
        <VStack align="stretch" spacing={4} flex="1" minH={0}>
          <HStack align="start" flexShrink={0}>
            <Text flex="1" fontSize="12px" color={colors.fg[3]}>
              Файлы аккаунта · доступны во всех чатах
            </Text>
            <IconButton size="workbench" px={0} variant="ghost" aria-label="Обновить библиотеку" title="Обновить библиотеку"
              icon={<FiRefreshCw />} isLoading={browser.loading} onClick={browser.refresh} />
          </HStack>
          <InputGroup flexShrink={0}>
            <Input ref={searchRef} aria-label="Поиск по библиотеке" placeholder="Найти файл по имени…"
              value={browser.query} maxLength={200} pr="44px" h="44px"
              onChange={event => browser.search(event.target.value)}
              onCompositionStart={() => browser.setComposing(true)}
              onCompositionEnd={() => browser.setComposing(false)} />
            {browser.query && <InputRightElement h="44px" w="44px">
              <IconButton aria-label="Очистить поиск по библиотеке" icon={<FiX />} variant="ghost" size="sm"
                onClick={() => { browser.search(''); searchRef.current?.focus(); }} />
            </InputRightElement>}
          </InputGroup>
          {hasThread ? <Box flexShrink={0}>
            <Text fontSize="12px" mb={1}>Куда добавить файл</Text>
            <AppSelect ariaLabel="Куда добавить файл" size="sm" value={targetValid ? destination : ''} options={options} menuPortalTarget={null}
              placeholder="Выберите назначение" isDisabled={copying} onChange={setDestination} />
          </Box> : <Text fontSize="12px" color={colors.fg[3]}>Для загрузки и добавления файлов выберите или создайте чат. Скачивание доступно без чата.</Text>}
          {blocked && <Text role="status" fontSize="12px" color={colors.warning}>
            Сначала сохраните правки и дождитесь завершения обработки. Просмотр и скачивание доступны.
          </Text>}
          {ideSelected && ideTarget?.blocked && !ideCopy.done && !ideCopy.uncertain && <Text role="status" fontSize="xs">Сохраните правки и дождитесь готовности репозитория IDE перед копированием.</Text>}
          {ideSelected && !targetValid && <Text role={destination === 'ide:pending' ? 'status' : 'alert'} fontSize="xs">{destination === 'ide:pending'
            ? 'Проверяю назначение IDE. Добавление станет доступно после готовности репозитория.'
            : 'Назначение IDE изменилось. Выберите его заново; файл не перенаправлен в другой проект.'}</Text>}
          {ideSelected && <IdeLibraryDestination copy={ideCopy} target={ideTarget} disabled={copyBlocked} />}
          <Box flex="1" minH={0}>
            <WorkLibraryPane work={ideCopy.busy ? { ...work, busy: `copy:${ideCopy.file?.file_id}` } : work} presentation="document" libraryOnlyUpload copyDisabled={copyBlocked || browser.loading}
              browser={browser}
              copyActionForItem={copyAction}
              uploadControl={<WorkFileUpload session={uploadSession} libraryOnly disabled={!hasThread || blocked} busy={copying} />} />
          </Box>
        </VStack>
      </DrawerBody>
    </DrawerContent>
  </Drawer>;
}
