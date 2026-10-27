import { Button, Icon, Text } from '@chakra-ui/react';
import { FiEye, FiRefreshCw } from '@shared/icons';
import { canPreviewBuild } from './PdfBuildActivity';
import { documentControls } from '@theme/tokens';

/** A read of the owned artifact, alongside compilation actions, never a build. */
export function PdfPreviewButton({ document, onOpenPdf, hintAvailable = false }) {
  const { build, previewUrl, previewBusy } = document;
  if (!canPreviewBuild(build) && !previewUrl) return null;
  const label = previewUrl ? 'Обновить PDF' : 'Открыть PDF';
  return <Button size="document" w={{ base: `${documentControls.mobile}px`, md: '144px' }} px={{ base: 0, md: 3 }}
    flexShrink={0} variant="workbenchSecondary" aria-label={label} title={label}
    data-action-hint={hintAvailable && !previewUrl && !previewBusy
      && build?.source_digest && build.source_digest === document.project?.source_digest ? 'idle' : undefined}
    onClick={onOpenPdf} isLoading={previewBusy} isDisabled={Boolean(previewUrl) && !canPreviewBuild(build)}>
    <Icon as={previewUrl ? FiRefreshCw : FiEye} />
    <Text as="span" ml={2} display={{ base: 'none', md: 'inline' }}>{label}</Text>
  </Button>;
}
