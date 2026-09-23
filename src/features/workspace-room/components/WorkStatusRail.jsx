import { Badge, Box, Button, HStack, Icon, IconButton, Text, Tooltip, VStack } from '@chakra-ui/react';
import { FiActivity, FiBookOpen, FiEdit3, FiFolder, FiRefreshCw } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { WORK_HUB_THEME } from '../model/theme';

const STATE_LABELS = {
  absent: 'не создано',
  unselected: 'выберите чат',
  expired: 'истекло',
  unavailable: 'недоступно',
};

function WorkspaceState({ state, recovered }) {
  if (state === 'ready') {
    return recovered
      ? <Badge data-testid="work-workspace-state" colorScheme="blue">восстановлено</Badge>
      : <Badge data-testid="work-workspace-state" colorScheme="green">временная среда</Badge>;
  }
  return (
    <Badge
      data-testid="work-workspace-state"
      colorScheme={state === 'unavailable' ? 'orange' : 'gray'}
    >
      {STATE_LABELS[state] || 'нет данных'}
    </Badge>
  );
}

function StatusFact({ label, value, icon }) {
  return (
    <HStack minW={0} spacing={1.5} color={colors.fg[4]}>
      <Icon as={icon} boxSize="12px" flexShrink={0} aria-hidden />
      <Text as="span" fontSize="10px" textTransform="uppercase" letterSpacing="0.04em">
        {label}
      </Text>
      <Text as="span" minW={0} noOfLines={1} fontSize="11px" color={colors.fg[2]}>
        {value}
      </Text>
    </HStack>
  );
}

export function WorkStatusRail({
  workspace,
  room,
  file,
  dirty,
  section,
  refreshing,
  onRefresh,
  showContextAction,
  contextButtonRef,
  onOpenContext,
}) {
  const source = section === 'library'
    ? 'Библиотека'
    : section === 'context' ? 'Контекст' : 'Рабочее место';
  const revision = String(file?.revision || workspace?.revision || '—');
  const editState = !file?.path
    ? 'файл не выбран'
    : dirty ? 'не сохранено' : file?.fence ? 'можно править' : 'только чтение';
  const roomState = room?.state === 'ready' ? 'на связи' : 'нет связи';

  return (
    <VStack
      data-testid="work-status-rail"
      flexShrink={0}
      align="stretch"
      spacing={0}
      bg={WORK_HUB_THEME.headerBg}
      borderBottom={`1px solid ${WORK_HUB_THEME.panelBorder}`}
    >
      <HStack minH="52px" px={{ base: 3, md: 5 }} py={2} justify="space-between" spacing={3}>
        <HStack spacing={2} minW={0} flex="1">
          <Box
            boxSize="28px"
            flexShrink={0}
            borderRadius={borderRadius.sm}
            bg={colors.accent.soft}
            display="grid"
            placeItems="center"
          >
            <Icon as={FiFolder} boxSize="15px" color={colors.blue[300]} />
          </Box>
          <Box minW={0}>
            <Text fontSize="13.5px" color={colors.fg[1]} fontWeight="650">Работа</Text>
            <Text display={{ base: 'none', sm: 'block' }} fontSize="10.5px" color={colors.fg[4]} noOfLines={1}>
              Временная среда чата и постоянная библиотека
            </Text>
          </Box>
          <WorkspaceState state={workspace?.state} recovered={workspace?.recovered} />
        </HStack>
        <HStack spacing={1} flexShrink={0}>
          {showContextAction && (
            <Button
              ref={contextButtonRef}
              size="xs"
              variant="ghost"
              leftIcon={<FiActivity />}
              onClick={onOpenContext}
            >
              Контекст
            </Button>
          )}
          <Tooltip label="Обновить рабочее состояние">
            <IconButton
              aria-label="Обновить рабочее состояние"
              icon={<FiRefreshCw />}
              variant="ghost"
              size="sm"
              onClick={onRefresh}
              isLoading={refreshing}
              color={colors.fg[3]}
            />
          </Tooltip>
        </HStack>
      </HStack>
      <HStack
        px={{ base: 3, md: 5 }}
        py={1.5}
        spacing={{ base: 3, md: 5 }}
        minW={0}
        overflowX="auto"
        borderTop={`1px solid ${colors.border.faint}`}
        sx={{ scrollbarGutter: 'stable' }}
      >
        <StatusFact label="Источник" value={source} icon={section === 'library' ? FiBookOpen : FiFolder} />
        <StatusFact label="Версия" value={revision === '—' ? revision : revision.slice(0, 12)} icon={FiRefreshCw} />
        <StatusFact label="Правка" value={editState} icon={FiEdit3} />
        <StatusFact label="Комната" value={roomState} icon={FiActivity} />
      </HStack>
    </VStack>
  );
}
