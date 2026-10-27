import { useEffect, useRef, useState } from 'react';
import { Badge, Box, Button, HStack, Icon, Spinner, Text, VStack } from '@chakra-ui/react';
import { FiCopy, FiDownload, FiFileText } from '@shared/icons';
import ActionLink from '@shared/controls/ActionLink';
import Pager from '@shared/controls/Pager';
import { ownedFileDownloadUrl } from '@api/fileDownload';
import { borderRadius, colors } from '@theme/tokens';
import { WORK_HUB_THEME, WORK_SCROLLBAR_SX } from '../model/theme';

const isAvailable = (item) => !item.availability || item.availability === 'ready';

const OUTCOME_LABELS = {
  library_saved: 'Источник сохранён только в библиотеке',
  library_uploaded: 'сохранён в библиотеке',
  imported: 'добавлен',
  kept: 'сохранён без перезаписи',
  conflict: 'нужно обновить',
  busy: 'занято агентом',
  unavailable: 'временно недоступно',
};

const outcomeScheme = (outcome) => {
  if (outcome === 'imported' || outcome === 'library_uploaded') return 'green';
  if (outcome === 'conflict' || outcome === 'busy' || outcome === 'library_saved') return 'orange';
  if (outcome === 'unavailable') return 'red';
  return 'gray';
};

export function LibraryPane({
  items = [],
  state = 'ready',
  loading = false,
  pageError = false,
  workspaceReady,
  hasThread,
  busy,
  copyDisabled = false,
  onCopy,
  onLoadMore,
  hasMore,
  uploadControl,
  outcomes = {},
  copyActionForItem,
  libraryOnlyUpload = false,
  presentation = 'work',
  browser,
}) {
  const [selectedId, setSelectedId] = useState('');
  const listRef = useRef(null);
  useEffect(() => { if (listRef.current) listRef.current.scrollTop = 0; }, [browser?.page, browser?.query]);
  const document = presentation === 'document';
  const actionProps = document ? {
    size: 'workbench', h: { base: '44px', md: '36px' }, minH: { base: '44px', md: '36px' },
    flex: '1 1 170px', minW: 0, mt: 0, w: 'auto', fontSize: '12.5px', fontWeight: 600, variant: 'workbenchSecondary',
  } : {};

  useEffect(() => {
    if (selectedId && !items.some((item) => item.file_id === selectedId)) {
      setSelectedId('');
    }
  }, [items, selectedId]);

  return (
    <VStack align="stretch" spacing={3} h="full" minH={0}>
    <VStack ref={listRef} align="stretch" spacing={document ? 4 : 2} flex="1" minH={0} overflow="auto" sx={{ ...WORK_SCROLLBAR_SX, '& > *': { flexShrink: 0 } }}>
      {document && libraryOnlyUpload
        ? <Text fontSize="11.5px" color={colors.fg[3]}>
          Загрузка только в Библиотеку. Добавление в проект — отдельно.
        </Text>
        : <Box px={3} py={2.5} borderRadius={borderRadius.md} bg={colors.accent.softest} border={`1px solid ${colors.accent.subtleBorder}`}>
          <Text fontSize="11.5px" color={colors.fg[3]}>{libraryOnlyUpload
            ? 'Библиотека постоянна. Новый файл сохраняется только здесь. Добавление в выбранный проект — отдельное действие.'
            : 'Библиотека постоянна. Новый файл сохраняется здесь и отдельной копией добавляется во временное рабочее место.'}</Text>
        </Box>}
      {uploadControl}
      {browser && loading && items.length > 0 && <Text role="status" fontSize="xs" color={colors.fg[3]}>Обновляю список файлов…</Text>}
      {browser && pageError && <Box role="status" p={3} borderRadius={borderRadius.md} bg={colors.warningSoft}>
        <Text fontSize="xs">Не удалось загрузить страницу. Последний доступный список сохранён.</Text>
        <Button mt={2} size="sm" variant="outline" onClick={browser.refresh}>Повторить загрузку файлов</Button>
      </Box>}
      {state === 'unavailable' && (
        <Box px={3} py={2.5} borderRadius={borderRadius.md} bg={colors.warningSoft} border={`1px solid ${colors.warningBorder}`}>
          <Text fontSize="11.5px" color={colors.fg[3]}>Библиотека временно недоступна. Рабочее место можно продолжать использовать.</Text>
        </Box>
      )}
      {state === 'stale' && (
        <Text fontSize="11px" color={colors.warning}>Показаны последние доступные данные библиотеки.</Text>
      )}
      {state !== 'unavailable' && items.length === 0 && (
        <HStack py={4} minH="52px" role="status" spacing={2}>
          {loading && <Spinner size="sm" aria-hidden="true" />}
          <Text fontSize="12.5px" color={colors.fg[4]}>
            {loading ? 'Загружаю библиотеку…' : pageError ? 'Список файлов недоступен.'
              : browser?.query.trim() ? 'Файлы с таким именем не найдены.' : 'В библиотеке пока нет доступных файлов.'}
          </Text>
        </HStack>
      )}
      {items.map((item) => {
        const copyAction = copyActionForItem?.(item);
        const outcome = copyAction ? copyAction.outcome : outcomes[item.file_id];
        const copying = busy === `copy:${item.file_id}`;
        return (
        <Box
          key={item.file_id}
          data-testid="work-library-file"
          data-selected={selectedId === item.file_id ? 'true' : 'false'}
          px={3}
          py={document ? 3 : 2.5}
          borderRadius={borderRadius.md}
          bg={selectedId === item.file_id ? colors.accent.softest : WORK_HUB_THEME.panelBg}
          border={`1px solid ${
            selectedId === item.file_id ? colors.accent.subtleBorder : colors.border.subtle
          }`}
        >
          <HStack spacing={2} minW={0}>
            <Icon as={FiFileText} color={colors.iris[300]} boxSize="14px" flexShrink={0} />
            <Text flex="1" minW={0} overflowWrap="anywhere" title={item.name} fontSize="12.5px" color={colors.fg[2]}>{item.name}</Text>
            {!document && <Badge colorScheme="blue" fontSize="9px">библиотека</Badge>}
          </HStack>
          <VStack mt={1.5} spacing={1} align="stretch" minW={0}>
            <Text fontSize="10px" color={colors.fg[3]} overflowWrap="anywhere">
              {item.file_type || 'файл'}{!isAvailable(item) ? ' · недоступен' : document ? '' : ' · доступен'}
            </Text>
            {outcome && (
              <Badge
                data-testid="work-library-outcome"
                colorScheme={outcomeScheme(outcome)}
                alignSelf="flex-start"
                maxW="full"
                whiteSpace="normal"
                overflowWrap="anywhere"
                textTransform="none"
              >
                {OUTCOME_LABELS[outcome] || 'статус обновлён'}
              </Badge>
            )}
          </VStack>
          <Box data-toast-protected-actions display="flex" flexWrap="wrap" gap="12px" mt={3} sx={{ '& > *': { minWidth: 0, maxWidth: '100%' } }}>
          {isAvailable(item) && ownedFileDownloadUrl(item.file_id) ? (
            <ActionLink
              href={ownedFileDownloadUrl(item.file_id)}
              isExternal
              aria-label={`Скачать ${item.name || 'файл'}`}
              mt={2.5}
              w="full"
              size="xs"
              variant="outline"
              leftIcon={<FiDownload />}
              onFocus={() => setSelectedId(item.file_id)}
              {...actionProps}
            >
              Скачать
            </ActionLink>
          ) : (
            <Text mt={2.5} fontSize="11px" color={colors.fg[4]}>
              Скачивание недоступно
            </Text>
          )}
          <Button mt={2.5} w="full" size="xs" leftIcon={copying ? <Spinner w="14px" h="14px" label="" aria-hidden="true" /> : <FiCopy />} onClick={(event) => {
            if (busy) return;
            setSelectedId(item.file_id);
            if (copyAction?.onCopy) copyAction.onCopy(item, event.currentTarget);
            else onCopy(item);
          }}
            onFocus={() => setSelectedId(item.file_id)}
            aria-busy={copying} aria-disabled={copying || undefined}
            isDisabled={!copying && (!hasThread || copyDisabled || copyAction?.disabled || Boolean(busy) || !isAvailable(item))}
            variant="outline" color={colors.blue[100]} borderColor={colors.accent.subtleBorder}
            aria-label={copyAction?.ariaLabel || (document ? workspaceReady ? 'Добавить в рабочее место' : 'Создать и добавить' : undefined)}
            transitionProperty="background-color, border-color, box-shadow"
            _hover={{ bg: colors.accent.hoverSoft }} {...actionProps}>
            {copyAction?.label || (workspaceReady ? document ? 'Добавить' : 'Добавить в рабочее место' : 'Создать и добавить')}
          </Button>
          </Box>
          {copyAction?.feedback && <Text role="status" fontSize="11px" mt={1} color={colors.fg[3]}>{copyAction.feedback}</Text>}
        </Box>
      ); })}
      {!browser && hasMore && (
        <Box>
          {pageError && (
            <Text role="status" mb={2} fontSize="11.5px" color={colors.warning}>
              Не удалось загрузить следующие файлы. Уже загруженные файлы доступны.
            </Text>
          )}
          <Button w="full" size="sm" variant="ghost" onClick={onLoadMore}
            isLoading={busy === 'library:more'} loadingText="Загружаю файлы…"
            isDisabled={Boolean(busy)}>
            {pageError ? 'Повторить загрузку файлов' : 'Показать ещё'}
          </Button>
        </Box>
      )}
    </VStack>
    {browser && <Box as="nav" aria-label="Страницы библиотеки" flexShrink={0} pt={3}
      borderTop="1px solid" borderColor={colors.border.subtle}>
      <Text role="status" fontSize="xs" color={colors.fg[3]} textAlign="center" mb={2}>
        {loading ? 'Загружаю страницу…' : `Страница ${browser.page + 1} · файлов: ${items.length}`}
      </Text>
      <Pager page={browser.page} hasMore={browser.hasMore} onChange={browser.goToPage} busy={loading || Boolean(busy)} />
    </Box>}
    </VStack>
  );
}
