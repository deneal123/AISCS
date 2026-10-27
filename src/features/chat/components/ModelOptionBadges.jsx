import { Box, HStack, Icon, Text } from '@chakra-ui/react';
import { FiArrowDownRight, FiArrowUpRight, FiEdit3, FiFile, FiImage, FiLayers, FiMic, FiTool } from '@shared/icons';
import { colors } from '@theme/tokens';

const CAPABILITIES = {
  vision: [FiImage, 'Изображения на входе'],
  audio: [FiMic, 'Аудио'],
  files: [FiFile, 'Файлы'],
  image_out: [FiEdit3, 'Создание изображений'],
  tools: [FiTool, 'Инструменты'],
};

export function modelBadges(info, context = '') {
  const badges = [];
  if (info?.is_free === true) badges.push({ key: 'free', text: true, label: 'Бесплатно', color: colors.success });
  else if (info?.cost_tier === 0) badges.push({ key: 'cost', icon: FiArrowDownRight, label: 'Экономная', color: colors.success });
  if (info?.cost_tier === 2) badges.push({ key: 'cost', icon: FiArrowUpRight, label: 'Повышенная стоимость', color: colors.warning });
  for (const capability of new Set(Array.isArray(info?.capabilities) ? info.capabilities : [])) {
    if (typeof capability !== 'string' || !Object.hasOwn(CAPABILITIES, capability)) continue;
    const [icon, label] = CAPABILITIES[capability];
    badges.push({ key: capability, icon, label });
  }
  if (context) badges.push({ key: 'context', icon: FiLayers, label: context });
  return badges;
}

/** Static metadata inside the library option, never nested buttons or tab stops. */
export default function ModelOptionBadges({ badges }) {
  return <HStack as="span" spacing={1} flexShrink={0} color={colors.fg[3]}>
    {badges.map(badge => badge.text ? <Text as="span" key={badge.key} fontSize="11px" color={badge.color}>{badge.label}</Text> : <Box as="span" key={badge.key} role="img" aria-label={badge.label}
      display="inline-flex" color={badge.color}>
      <Icon as={badge.icon} boxSize={3} aria-hidden="true" />
    </Box>)}
  </HStack>;
}
