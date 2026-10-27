import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Box, Button, Flex, HStack, Icon, Text } from '@chakra-ui/react';
import { FiCode, FiRefreshCw, FiX } from '@shared/icons';
import AppLoading from '@shared/controls/AppLoading';
import CodePreview from '@shared/controls/CodePreview';
import { colors, typography } from '@theme/tokens';
import { ideCodeLanguage } from '../model/ideCodeLanguage';
import { IDE_OPEN_FILE_LIMIT } from '../model/useIdeRepositoryReads';
import { WORK_SCROLLBAR_SX } from '../model/theme';
import { WorkspaceEditor } from './WorkspaceEditor';
import IdeMoveFileButton from './IdeMoveFileButton';

const codeStyle = { margin: 0, padding: '16px', minWidth: '100%', width: 'max-content',
  fontFamily: typography.fontFamily.mono, fontSize: '12px', lineHeight: 1.7 };
const IdeMarkdownPreview = lazy(() => import('./IdeMarkdownPreview'));

export default function IdeCodePane({ reads, focusRef, editor, onCreate, onBrowse, onMove, singlePane = false, safeBottom = false }) {
  const file = reads.file;
  const language = ideCodeLanguage(file?.path);
  const [preview, setPreview] = useState(false);
  const markdown = /\.(?:md|markdown)$/i.test(file?.path || '') && file?.kind === 'text';
  useEffect(() => setPreview(false), [file?.path]);
  const navigationRef = useRef(null);
  useEffect(() => { if (editor?.file?.path) editor.editorRef.current?.focus(); }, [editor?.file?.path, editor?.editorRef]);
  useEffect(() => {
    navigationRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [file?.path]);
  const closeFile = (path, event) => {
    // Closing a tab must not strand keyboard focus on a removed button.
    if (event.currentTarget === document.activeElement) focusRef.current?.focus();
    reads.close(path);
  };
  return <Flex ref={focusRef} tabIndex={-1} role="region" aria-label="Просмотр исходника" direction="column" h="full" minH={0} minW={0}
    pb={safeBottom ? 'var(--app-safe-bottom, 0px)' : 0}
    sx={{ containerType: 'inline-size', containerName: 'ide-file-pane' }}
    _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
    <Flex flexShrink={0} minW={0} borderBottom="1px solid" borderColor={colors.border.subtle}>
      <HStack ref={navigationRef} as="nav" aria-label="Открытые файлы" spacing={0} flex="1" minW={0} overflowX="auto" sx={WORK_SCROLLBAR_SX}>
        {reads.files.map((item) => <HStack key={item.path} spacing={0} flexShrink={0} maxW="240px"
          borderRight="1px solid" borderColor={colors.border.subtle}
          borderBottom="2px solid" borderBottomColor={file?.path === item.path ? colors.blue[300] : 'transparent'}
          bg={file?.path === item.path ? colors.bg.input : 'transparent'}>
          <Button size="document" variant="ghost" minW={0} justifyContent="start" borderRadius={0}
            aria-label={`Показать ${item.path}`} aria-current={file?.path === item.path ? 'page' : undefined}
            title={item.path} isDisabled={reads.loading || Boolean(editor?.busy)} onClick={() => reads.open(item.path)}>
            <Icon as={FiCode} mr={2} boxSize={3.5} flexShrink={0} color={colors.fg[3]} />
            <Text as="span" isTruncated>{item.path.split('/').pop()}</Text>
          </Button>
          <Button size="document" variant="ghost" px={1} minW={{ base: '30px', md: '34px' }} borderRadius={0}
            aria-label={`Закрыть ${item.path}`} title="Закрыть файл"
            isDisabled={reads.loading || reads.fileLoading || Boolean(editor?.busy)} onClick={(event) => closeFile(item.path, event)}>
            <Icon as={FiX} boxSize={3} />
          </Button>
        </HStack>)}
        {!reads.files.length && <Text px={3} py={2} fontSize="xs" color={colors.fg[3]}>Исходники</Text>}
      </HStack>
      {file && onMove && singlePane && <IdeMoveFileButton isDisabled={Boolean(editor?.busy || reads.loading || editor?.canMove === false)} onClick={onMove} />}
      {file && <Button size="document" variant="ghost" flexShrink={0} aria-label="Обновить файл" title="Обновить файл"
        isDisabled={reads.fileLoading || reads.loading || Boolean(editor?.busy)} onClick={() => reads.open(file.path, { refresh: true })}>
        <Icon as={FiRefreshCw} boxSize={3.5} />
      </Button>}
    </Flex>
    {file && !editor?.file && <Flex px={3} py={1.5} gap={2} align="center" flexWrap="wrap" borderBottom="1px solid" borderColor={colors.border.subtle} flexShrink={0}>
      <Text flex="1" minW={0} fontSize="xs" color={colors.fg[3]} overflowWrap="anywhere" noOfLines={2} title={file.path}>{file.path.split('/').join(' / ')}</Text>
      {markdown && <HStack role="group" aria-label="Вид Markdown" spacing={1}>
        <Button size="document" variant={!preview ? 'workbenchPrimary' : 'ghost'} aria-pressed={!preview} onClick={() => setPreview(false)}>Код</Button>
        <Button size="document" variant={preview ? 'workbenchPrimary' : 'ghost'} aria-pressed={preview} onClick={() => setPreview(true)}>Превью</Button>
      </HStack>}
    </Flex>}
    {reads.fileLoading && <Box px={3} py={2} flexShrink={0}><AppLoading label="Открываю файл…" /></Box>}
    {editor?.file ? <Box flex="1" minH={0}><WorkspaceEditor variant="ide" file={editor.file} dirty={editor.dirty} busy={editor.busy} writeBlocked={editor.writeBlocked}
      conflict={editor.conflict} canInspect={editor.canInspect} canReacquire={editor.canReacquire}
      onInspect={editor.inspect} onCopyDraft={editor.copyDraft} onLoadActual={editor.loadActual}
      onChange={editor.change} onSave={editor.save} onDiscard={editor.discard} onReacquire={() => editor.edit(editor.file)} editorRef={editor.editorRef} /></Box>
      : !file ? <Box p={4} overflowY="auto"><Icon as={FiCode} boxSize={6} color={colors.fg[3]} mb={3} aria-hidden="true" /><Text as="h2" fontSize="sm" fontWeight={600} mb={2}>Откройте исходник</Text><Text fontSize="sm" color={colors.fg[3]}>{reads.runtime?.state === 'expired'
        ? 'Ранее открытые файлы доступны для просмотра. Сохранённые версии — в истории проекта.'
        : 'Выберите файл в дереве или создайте новый.'}</Text>
        {singlePane && onBrowse && <Button mt={3} size="document" variant="workbenchSecondary" onClick={onBrowse}
          data-action-hint={reads.runtime?.state === 'ready' && !reads.loading && !reads.fileLoading && !editor?.busy ? 'idle' : undefined}>Открыть файлы</Button>}
        {onCreate && reads.runtime?.state !== 'expired' && <Button mt={3} size="document" variant="workbenchPrimary" isDisabled={Boolean(editor?.busy)} onClick={onCreate}>Создать файл</Button>}
      </Box>
      : file.kind === 'binary' ? <Text p={4} fontSize="sm" color={colors.fg[3]}>Это двоичный файл. Текстовый просмотр недоступен.</Text>
      : <>
        {file.truncated && <Text px={3} py={2} fontSize="xs" color={colors.warning} role="status">Показано начало большого файла, не полное содержимое.</Text>}
        <Box flex="1" minH={0} minW={0} overflow="auto" role="region" tabIndex={0}
          aria-label={`${markdown && preview ? 'Превью Markdown' : 'Код файла'} ${file.path}`} sx={WORK_SCROLLBAR_SX}
          _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
          {markdown && preview ? <Suspense fallback={<AppLoading label="Открываю превью Markdown…" />}>
            <IdeMarkdownPreview file={file} onOpen={reads.open} />
          </Suspense> : <CodePreview key={file.path} language={language} value={file.content || ''} showLineNumbers customStyle={codeStyle} />}
        </Box>
      </>}
    {file && !editor?.file && <Flex px={3} py={1} mt="auto" gap={3} flexShrink={0} align="center" borderTop="1px solid" borderColor={colors.border.subtle}>
      <Text fontSize="xs" color={colors.fg[3]}>Только просмотр</Text>
      {editor && !editor.file && file.kind === 'text' && !file.truncated && <Button size="document" variant="workbenchSecondary" isDisabled={Boolean(editor.busy)} onClick={() => editor.edit(file)}>Редактировать</Button>}
      <Text fontSize="xs" color={colors.fg[3]} ml="auto">{file.kind === 'binary' ? 'Двоичный файл' : language || 'Текст'}</Text>
      <Text fontSize="xs" color={colors.fg[3]} title="Открытые файлы, максимум 8">{reads.files.length}/{IDE_OPEN_FILE_LIMIT}</Text>
    </Flex>}
    {editor?.error && <Text role="alert" px={3} py={2} fontSize="xs" color={colors.warning}>{editor.error}</Text>}
    {editor?.outcome && <Text role="status" px={3} py={1} fontSize="xs" color={colors.fg[3]}>{editor.outcome}</Text>}
  </Flex>;
}
