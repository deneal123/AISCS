import { Flex, HStack, Spinner, Text } from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { safeBuildLabel } from './DocumentForgePanel';

export const PDF_BUILD_RUNNING = new Set(['queued', 'preparing', 'building', 'deterministic_audit', 'visual_audit', 'publishing']);
export const canPreviewBuild = (build) => Boolean(build?.artifacts?.some((item) => item.role === 'pdf')
  && ['preview_ready', 'visual_pending', 'visual_audit', 'ready'].includes(build?.state));
const RUN_LABELS = {
  queued: 'Сборка PDF в очереди', preparing: 'Подготавливаю PDF…', building: 'Собираю PDF…',
  deterministic_audit: 'Техническая проверка PDF…', visual_audit: 'Визуальная проверка PDF…',
  publishing: 'Сохраняю PDF…',
};

/** Always-visible projection of the existing build owner, never a second poller. */
export function PdfBuildActivity({ document, initialLabel }) {
  const { build, busy, previewUrl, previewError } = document;
  const running = PDF_BUILD_RUNNING.has(build?.state);
  const pending = ['build', 'final', 'cancel'].includes(busy);
  const canOpen = canPreviewBuild(build) || Boolean(previewUrl);
  if (!build && !pending && !canOpen && !initialLabel) return null;
  const label = busy === 'cancel' ? 'Отменяю сборку…'
    : running ? RUN_LABELS[build.state]
      : pending ? busy === 'final' ? 'Запускаю проверку финала…' : 'Запускаю сборку PDF…'
        : build?.state ? safeBuildLabel(build.state) : initialLabel;
  return <Flex data-testid="pdf-build-activity" gap={2} align="center" justify="flex-end" flexWrap="wrap" minW={0}>
    <HStack minW={0} spacing={2} role="status" aria-live="polite" aria-atomic="true">
      {(running || pending) && <Spinner size="xs" label="" flexShrink={0} color={colors.blue[500]} aria-hidden="true" />}
      <Text fontSize="12px" color={build?.state === 'failed' && !pending ? colors.warning : colors.fg[3]}>{label}</Text>
    </HStack>
    {previewError && <Text role="alert" w="full" fontSize="12px" color={colors.warning}>
      Не удалось открыть превью. Повторите открытие.
    </Text>}
  </Flex>;
}
