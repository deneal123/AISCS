import { useEffect, useState } from 'react';
import { Badge, Box, Button, HStack, Spinner, Text, VStack } from '@chakra-ui/react';
import { FiCopy, FiRefreshCw, FiRotateCcw } from '@shared/icons';
import AppTextarea from '@shared/controls/AppTextarea';
import { borderRadius, colors, typography } from '@theme/tokens';
import { WORK_HUB_THEME, WORK_SCROLLBAR_SX } from '../model/theme';
import { LEASE_REASON_LABELS } from '../model/constants';
import { LatexSourcePreview } from './LatexSourcePreview';

const LATEX_SOURCE = /\.(?:tex|bib|cls|sty)$/i;

export function WorkspaceEditor({
  file,
  dirty,
  busy,
  writeBlocked = false,
  conflict,
  revert,
  onChange,
  onSave,
  onDiscard,
  onReacquire,
  onCopyDraft,
  onInspect,
  canInspect = true,
  canReacquire = true,
  onLoadActual,
  onCloseRevert,
  onApplyRevert,
  editorRef,
  variant = 'workspace',
}) {
  const ide = variant === 'ide';
  const controlSize = ide ? 'document' : 'xs';
  const recoveryTransition = ide ? 'background-color, border-color, box-shadow' : undefined;
  const [previewSource, setPreviewSource] = useState(false);
  const supportsHighlight = LATEX_SOURCE.test(file.path || '');
  useEffect(() => setPreviewSource(false), [file.path]);
  const canSave = Boolean(dirty && file.fence && !file.truncated && !writeBlocked && (ide ? !busy : busy !== 'save'));
  const handleEditorKeyDown = (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (canSave) onSave();
    }
  };

  if (!file.path) {
    return <VStack justify="center" h="full" px={8} align="start" spacing={2}>
      <Text fontSize="15px" color={colors.fg[2]}>Выберите файл из рабочего места</Text>
      <Text fontSize="12.5px" color={colors.fg[4]}>Здесь можно просмотреть и сохранить правки. Команды по-прежнему выполняются через агента в чате.</Text>
    </VStack>;
  }
  return (
    <VStack align="stretch" h="full" spacing={0} minW={0} minH={0} overflowY={ide && conflict ? 'auto' : undefined}>
      <HStack px={4} minH={ide ? '34px' : '44px'} flexShrink={0} borderBottom={`1px solid ${colors.border.subtle}`} justify="space-between" flexWrap="wrap">
        <Text minW={0} flex="1" noOfLines={1} fontSize="12.5px" color={colors.fg[2]}>{file.path}</Text>
        {supportsHighlight && (
          <Button size={controlSize} variant="ghost" onClick={() => setPreviewSource((value) => !value)}>
            {previewSource ? 'Редактировать' : 'Подсветка LaTeX'}
          </Button>
        )}
        <Badge colorScheme={file.fence ? 'green' : 'orange'}>
          {file.fence ? 'ваша правка' : 'только чтение'}
        </Badge>
      </HStack>
      {file.loading && <HStack px={4} py={3}><Spinner size="sm" color={colors.iris[300]} /><Text fontSize="12px" color={colors.fg[4]}>Загружаю файл…</Text></HStack>}
      {file.error && <Text px={4} py={3} fontSize="12px" color={colors.fg[4]}>Не удалось прочитать файл.</Text>}
      {!file.loading && !file.error && <>
        {!file.fence && !file.truncated && (!ide || !conflict) && (
          <HStack data-toast-protected-actions px={4} py={2.5} flexShrink={0} flexWrap="wrap" justify="space-between" bg={colors.warningSoft} borderBottom={`1px solid ${colors.warningBorder}`}>
            <Text fontSize="11.5px" color={colors.fg[3]}>
              {LEASE_REASON_LABELS[file.leaseReason]
                || (ide ? 'Текст остаётся в этом окне. Запись недоступна до проверки среды и файла.' : 'Право на правку потеряно. Текст редактора сохранён.')}
            </Text>
            <Button size={controlSize} variant="outline" transitionProperty={recoveryTransition} onClick={onReacquire} isDisabled={ide && (Boolean(busy) || !canReacquire)} leftIcon={<FiRefreshCw />}>
              Получить право
            </Button>
            {ide && !conflict && <HStack flexWrap="wrap">
              <Button size={controlSize} variant="outline" transitionProperty={recoveryTransition} onClick={onCopyDraft} isDisabled={Boolean(busy)}>Скопировать черновик</Button>
              <Button size={controlSize} variant="outline" transitionProperty={recoveryTransition} onClick={onInspect} isDisabled={Boolean(busy) || !canInspect}>Сверить с файлом</Button>
            </HStack>}
          </HStack>
        )}
        {conflict && (
          <Box data-toast-protected-actions mx={3} mt={3} p={3} borderRadius={borderRadius.md} bg={colors.warningSoft} border={`1px solid ${colors.warningBorder}`}
            role={ide ? 'region' : undefined} aria-label={ide ? 'Сверка файла' : undefined} aria-busy={ide && Boolean(busy)}
            display={ide ? 'flex' : undefined} flexDirection={ide ? 'column' : undefined}
            maxH={ide ? 'min(240px, 32dvh)' : undefined} minH={ide ? '148px' : undefined} flexShrink={ide ? 0 : undefined}>
            <HStack justify="space-between" flexShrink={0}>
              <Text as={ide ? 'h3' : undefined} fontSize="12px" fontWeight="600" color={colors.fg[2]}>{ide ? 'Сверка файла' : 'Версия файла изменилась'}</Text>
              {ide && <HStack spacing={1}>
                <Button size={controlSize} variant="workbenchSecondary" transitionProperty={recoveryTransition} onClick={onReacquire}
                  isDisabled={Boolean(busy) || !canReacquire}>Получить право</Button>
                <Button size={controlSize} variant="ghost" transitionProperty={recoveryTransition} onClick={onInspect} isDisabled={Boolean(busy) || !canInspect}
                  aria-label="Сверить с файлом" title="Сверить с файлом" px={2}><FiRefreshCw /></Button>
              </HStack>}
            </HStack>
            <Text mt={1} fontSize="11px" color={colors.fg[3]}>
              {ide ? conflict.notice : 'Ваши изменения не перезаписаны. Скопируйте их или явно загрузите актуальную версию.'}
            </Text>
            {ide && busy === 'inspect' && <Text mt={1} fontSize="xs" role="status">Сверяю файл…</Text>}
            {!ide && conflict.diff && <Text as="pre" mt={2} maxH="110px" overflow="auto" whiteSpace="pre-wrap" fontSize="10.5px" sx={WORK_SCROLLBAR_SX}>{conflict.diff}</Text>}
            <HStack mt={3} wrap="wrap" flexShrink={0}>
              <Button size={controlSize} variant="outline" transitionProperty={recoveryTransition} leftIcon={<FiCopy />} onClick={onCopyDraft} isDisabled={ide && Boolean(busy)}>
                {ide ? 'Скопировать черновик' : 'Скопировать мои изменения'}
              </Button>
              <Button size={controlSize} variant={ide ? 'workbenchSecondary' : undefined} colorScheme={ide ? undefined : 'orange'} transitionProperty={recoveryTransition}
                leftIcon={<FiRefreshCw />} onClick={onLoadActual} isDisabled={conflict.actualContent == null || (ide && (Boolean(busy) || !canInspect))}>
                {ide ? 'Загрузить версию' : 'Загрузить актуальную'}
              </Button>
            </HStack>
            {ide && conflict.diff && <Text as="pre" mt={2} flex="1" minH="32px" maxH="110px" overflow="auto" whiteSpace="pre-wrap" overflowWrap="anywhere"
              fontSize="10.5px" sx={WORK_SCROLLBAR_SX} role="region" aria-label="Сравнение версий файла" tabIndex={0}>{conflict.diff}</Text>}
          </Box>
        )}
        <Text
          px={4}
          py={2}
          fontSize="11px"
          color={file.truncated ? colors.warning : colors.fg[4]}
          role="status"
          aria-live="polite"
        >
          {file.truncated
            ? 'Файл показан не полностью и защищён от перезаписи.'
            : ide && file.detached ? 'Текст из прежней среды остаётся в этом окне. Скопируйте его перед уходом.'
            : ide && writeBlocked ? 'Команда агента использует файлы среды. Текст можно менять; запись временно недоступна.'
            : dirty
              ? file.stale ? 'Есть несохранённые изменения; рабочая версия обновилась.' : 'Есть несохранённые изменения.'
              : ide ? 'Копия во временной среде. Git-коммит автоматически не создаётся.' : 'Сохранено.'}
        </Text>
        {previewSource ? (
          <LatexSourcePreview
            value={file.content}
            label={`Подсвеченный исходник ${file.path}`}
          />
        ) : <AppTextarea
          ref={editorRef}
          aria-label={`Содержимое ${file.path}`}
          aria-readonly={file.truncated || !file.fence || Boolean(ide && busy)}
          value={file.content}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleEditorKeyDown}
          isReadOnly={file.truncated || !file.fence || Boolean(ide && busy)}
          flex="1"
          minH={ide && conflict ? '80px' : 0}
          flexShrink={ide && conflict ? 0 : undefined}
          borderRadius={0}
          border="0"
          bg={WORK_HUB_THEME.inputBg}
          color={colors.fg[2]}
          fontFamily={typography.fontFamily.mono}
          fontSize="12px"
          sx={{
            ...WORK_SCROLLBAR_SX,
            '&:focus': { boxShadow: `inset 0 0 0 1px ${colors.accent.subtleBorder}` },
          }}
        />}
        <HStack
          data-testid="workspace-editor-actions"
          data-toast-protected-actions
          px={3}
          pt={3}
          pb="calc(12px + env(safe-area-inset-bottom, 0px))"
          flexShrink={0}
          borderTop={`1px solid ${colors.border.subtle}`}
          bg={colors.bg.sticky}
          justify="flex-end"
          position="sticky"
          bottom={0}
        >
          <Button size={ide ? 'document' : 'sm'} variant="ghost" onClick={onDiscard} isDisabled={ide ? Boolean(busy) : !dirty || busy === 'save'}>Отменить</Button>
          <Button
            aria-label={ide ? 'Записать в среду' : 'Сохранить'}
            size={ide ? 'document' : 'sm'}
            variant="workbenchPrimary"
            onClick={onSave}
            isLoading={busy === 'save'}
            isDisabled={!canSave}
          >
            {ide ? 'Записать в среду' : 'Сохранить'}
            <Text as="span" ml={2} fontSize="10px" color="inherit">
              Ctrl+S
            </Text>
          </Button>
        </HStack>
      </>}
      {revert && <Box mx={3} mb={3} p={3} borderRadius={borderRadius.md} bg={colors.warningSoft} border={`1px solid ${colors.warningBorder}`}>
        <HStack justify="space-between" mb={2}><Text fontSize="12px" color={colors.fg[2]}>Изменения перед откатом</Text><Button size="xs" variant="ghost" onClick={onCloseRevert}>Закрыть</Button></HStack>
        <Text as="pre" maxH="160px" overflow="auto" whiteSpace="pre-wrap" fontSize="10.5px" sx={WORK_SCROLLBAR_SX}>{revert.diff || 'Отличий нет.'}</Text>
        <HStack mt={3} justify="flex-end"><Button size="xs" colorScheme="red" leftIcon={<FiRotateCcw />} onClick={onApplyRevert} isLoading={busy === `revert:${revert.ref}`}>Подтвердить откат</Button></HStack>
      </Box>}
    </VStack>
  );
}
