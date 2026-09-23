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
  conflict,
  revert,
  onChange,
  onSave,
  onDiscard,
  onReacquire,
  onCopyDraft,
  onLoadActual,
  onCloseRevert,
  onApplyRevert,
  editorRef,
}) {
  const [previewSource, setPreviewSource] = useState(false);
  const supportsHighlight = LATEX_SOURCE.test(file.path || '');
  useEffect(() => setPreviewSource(false), [file.path]);
  const canSave = Boolean(dirty && file.fence && !file.truncated && busy !== 'save');
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
    <VStack align="stretch" h="full" spacing={0} minW={0}>
      <HStack px={4} h="44px" flexShrink={0} borderBottom={`1px solid ${colors.border.subtle}`} justify="space-between">
        <Text minW={0} flex="1" noOfLines={1} fontSize="12.5px" color={colors.fg[2]}>{file.path}</Text>
        {supportsHighlight && (
          <Button size="xs" variant="ghost" onClick={() => setPreviewSource((value) => !value)}>
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
        {!file.fence && !file.truncated && (
          <HStack px={4} py={2.5} justify="space-between" bg={colors.warningSoft} borderBottom={`1px solid ${colors.warningBorder}`}>
            <Text fontSize="11.5px" color={colors.fg[3]}>
              {LEASE_REASON_LABELS[file.leaseReason]
                || 'Право на правку потеряно. Текст редактора сохранён.'}
            </Text>
            <Button size="xs" variant="outline" onClick={onReacquire} leftIcon={<FiRefreshCw />}>
              Получить право
            </Button>
          </HStack>
        )}
        {conflict && (
          <Box mx={3} mt={3} p={3} borderRadius={borderRadius.md} bg={colors.warningSoft} border={`1px solid ${colors.warningBorder}`}>
            <Text fontSize="12px" fontWeight="600" color={colors.fg[2]}>Версия файла изменилась</Text>
            <Text mt={1} fontSize="11px" color={colors.fg[3]}>
              Ваши изменения не перезаписаны. Скопируйте их или явно загрузите актуальную версию.
            </Text>
            {conflict.diff && (
              <Text as="pre" mt={2} maxH="110px" overflow="auto" whiteSpace="pre-wrap" fontSize="10.5px" sx={WORK_SCROLLBAR_SX}>
                {conflict.diff}
              </Text>
            )}
            <HStack mt={3} wrap="wrap">
              <Button size="xs" variant="outline" leftIcon={<FiCopy />} onClick={onCopyDraft}>
                Скопировать мои изменения
              </Button>
              <Button size="xs" colorScheme="orange" leftIcon={<FiRefreshCw />} onClick={onLoadActual} isDisabled={conflict.actualContent == null}>
                Загрузить актуальную
              </Button>
            </HStack>
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
            : dirty
              ? file.stale ? 'Есть несохранённые изменения; рабочая версия обновилась.' : 'Есть несохранённые изменения.'
              : 'Сохранено.'}
        </Text>
        {previewSource ? (
          <LatexSourcePreview
            value={file.content}
            label={`Подсвеченный исходник ${file.path}`}
          />
        ) : <AppTextarea
          ref={editorRef}
          aria-label={`Содержимое ${file.path}`}
          aria-readonly={file.truncated || !file.fence}
          value={file.content}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleEditorKeyDown}
          isReadOnly={file.truncated || !file.fence}
          flex="1"
          minH={0}
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
          <Button size="sm" variant="ghost" onClick={onDiscard} isDisabled={!dirty || busy === 'save'}>Отменить</Button>
          <Button
            aria-label="Сохранить"
            size="sm"
            colorScheme="blue"
            onClick={onSave}
            isLoading={busy === 'save'}
            isDisabled={!canSave}
          >
            Сохранить
            <Text as="span" ml={2} fontSize="10px" color="inherit" opacity={0.72}>
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
