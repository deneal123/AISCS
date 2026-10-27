import { Box, Button, Flex, HStack, Icon, Text } from '@chakra-ui/react';
import { FiFolder, FiPlus, FiRefreshCw, FiShield, FiSliders } from '@shared/icons';
import AppSelect from '@shared/controls/AppSelect';
import WorkbenchInfoPopover from '@shared/controls/WorkbenchInfoPopover';
import { useResponsive } from '@hooks/useResponsive';
import { colors } from '@theme/tokens';
import { PdfPreviewButton } from './PdfPreviewButton';

export function PdfStudioToolbar({ document, projects, dirty, assistantRunning, running, blocked, newDocumentBlocked = blocked, onPanel, onOpenPdf, onNewDocument }) {
  const { isMobile } = useResponsive();
  const project = document.project;
  const buttons = { size: 'document' };
  return <Flex data-testid="pdf-studio-toolbar" flexWrap="wrap" align="center"
    px={3} py={{ base: 1, md: 2 }} gap={{ base: 1.5, md: 2 }} flexShrink={0} borderBottom="1px solid" borderColor={colors.border.subtle}>
    <HStack spacing={1} minW={0} flex={{ base: '1 0 100%', md: '1 1 360px' }}>
      <Box data-testid="pdf-project-selector" minW={0} flex="1" maxW={{ base: 'none', md: '320px' }}>
        <AppSelect ariaLabel="Проект PDF" value={project?.path || ''} options={projects} size="document"
          placeholder="Выберите проект" isDisabled={dirty || Boolean(document.busy) || assistantRunning || document.projectState === 'loading'}
          onChange={document.selectProject} />
      </Box>
      {onNewDocument && <Button {...buttons} variant="ghost" px={2} gap={1.5} aria-label="Новый документ" title="Новый документ"
        isDisabled={newDocumentBlocked || assistantRunning} onClick={onNewDocument}>
        <Icon as={FiPlus} boxSize={4} /><Text as="span" display={{ base: 'none', md: 'inline' }}>Новый документ</Text>
      </Button>}
      {[['Материалы', FiFolder, false], ['Оформление', FiSliders, !project || blocked || assistantRunning]].map(([label, icon, disabled]) => (
        <Button key={label} {...buttons} px={2} gap={{ base: 0, md: 1.5 }} variant="ghost"
          aria-label={label} title={label} isDisabled={disabled} onClick={(event) => onPanel(label, event.currentTarget)}>
          <Icon as={icon} boxSize={4} flexShrink={0} />
          <Text as="span" display={{ base: 'none', md: 'inline' }}>{label}</Text>
        </Button>
      ))}
      <WorkbenchInfoPopover label="Работа PDF и расход кредитов" title="Работа с PDF">
        <Text data-testid="pdf-tools-consent-notice">
          В PDF-студии инструменты запускаются без дополнительных подтверждений и могут расходовать кредиты.
          Действуют тарифы и лимиты аккаунта.
        </Text>
      </WorkbenchInfoPopover>
    </HStack>
    <HStack spacing={2} flex={{ base: '1 0 100%', md: '0 0 auto' }} ml={{ base: 0, md: 'auto' }}>
      {running ? <Button {...buttons} flex={{ base: '1', md: 'initial' }} variant="workbenchSecondary"
          aria-busy={document.busy === 'cancel'}
          isDisabled={!document.build?.build_id || Boolean(document.busy)} onClick={document.cancelBuild}>Отменить сборку</Button>
        : <Button {...buttons} flex={{ base: '1', md: 'initial' }} variant="workbenchPrimary" leftIcon={isMobile ? undefined : <FiRefreshCw />}
          isDisabled={!project || blocked} aria-busy={document.busy === 'build'} onClick={() => document.buildProject(false)}>Собрать черновик</Button>}
      <Button {...buttons} flex={{ base: '1', md: 'initial' }} variant="workbenchSecondary" leftIcon={isMobile ? undefined : <FiShield />}
        isDisabled={!project || blocked} aria-busy={document.busy === 'final'} onClick={() => document.buildProject(true)}>Проверить финал</Button>
      <PdfPreviewButton document={document} onOpenPdf={onOpenPdf} hintAvailable={!dirty && !blocked && !running && !assistantRunning} />
    </HStack>
  </Flex>;
}
