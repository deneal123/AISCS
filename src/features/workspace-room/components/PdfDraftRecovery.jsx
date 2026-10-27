import { useState } from 'react';
import { Button, HStack, IconButton, Text, Tooltip } from '@chakra-ui/react';
import { FiDownload, FiRefreshCw } from '@shared/icons';
import { colors } from '@theme/tokens';
import { downloadLocalPdfDraft } from '../model/pdfDraftRecovery';

export function PdfDraftRecovery({ work, draft, mode }) {
  const [failed, setFailed] = useState(false);
  const state = work.hub?.workspace?.state;
  const workspaceIssue = state !== 'ready';
  const projectIssue = work.document.projectState === 'unavailable';
  const contentIssue = work.document.authoring?.state === 'unavailable';
  if (!workspaceIssue && !projectIssue && !contentIssue) return null;
  const source = mode === 'latex';
  const available = source ? work.file?.path && !work.file.loading && !work.file.truncated : Boolean(draft);
  const retry = workspaceIssue ? work.load : projectIssue ? work.document.loadProject : work.document.loadAuthoring;
  return <HStack data-testid="pdf-draft-recovery" role="status" flexShrink={0} px={3} py={2}
    spacing={2} flexWrap="wrap" borderBottom="1px solid" borderColor={colors.border.subtle}>
    <Text flex="1" minW="160px" fontSize="12px" color={colors.warning}>
      {state === 'expired' ? 'Среда завершена. Черновик остаётся в этом окне.'
        : workspaceIssue ? 'Среда недоступна. Черновик остаётся в этом окне.'
          : 'Сведения о документе не обновлены. Локальные правки остаются здесь.'}
    </Text>
    {available && <Tooltip maxW="min(240px, calc(100vw - 24px))" whiteSpace="normal"
      label={source ? 'Копия загруженного исходника.' : 'Текст и структура (JSON), без файлов вложений.'}>
      <Button size="document" variant="ghost" leftIcon={<FiDownload />} aria-label={source ? 'Скачать исходник' : 'Скачать черновик JSON'}
        onClick={() => { try { setFailed(!downloadLocalPdfDraft({ draft, file: work.file, mode })); } catch { setFailed(true); } }}>
        {source ? 'Скачать исходник' : 'Скачать черновик'}
      </Button>
    </Tooltip>}
    <IconButton size="document" px={0} variant="ghost" icon={<FiRefreshCw />}
      aria-label="Повторить подключение" title="Повторить подключение" isDisabled={!retry}
      isLoading={Boolean(work.hub.refreshing || work.document.projectState === 'refreshing')}
      onClick={() => retry?.()} />
    {failed && <Text role="alert" w="full" fontSize="12px" color={colors.warning}>Не удалось скачать копию. Текст остаётся в редакторе.</Text>}
  </HStack>;
}
