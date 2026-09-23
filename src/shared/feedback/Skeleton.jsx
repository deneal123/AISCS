import React from 'react';
import { Box } from '@chakra-ui/react';
import { borderRadius as radii } from '@theme/tokens';

/**
 * Брендовый skeleton-плейсхолдер загрузки: стеклянный блок с бегущим iris-бликом
 * (класс `.skeleton` в src/styles/motion.css; на reduced-motion — плоский блок).
 *
 * Живёт в shared/feedback (не shared/ui), чтобы фичи могли импортировать —
 * ESLint запрещает фичам тянуть пути с сегментом ui.
 */
export function Skeleton({ w = '100%', h = '14px', radius = radii.sm, ...rest }) {
  return <Box className="skeleton" w={w} h={h} borderRadius={radius} aria-hidden {...rest} />;
}

export default Skeleton;
