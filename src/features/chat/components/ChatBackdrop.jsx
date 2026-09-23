import React, { memo } from 'react';
import { keyframes } from '@emotion/react';
import { Box } from '@chakra-ui/react';
import { gradients } from '@theme/tokens';

// Очень медленный дрейф верхнего свечения — «дышащая» глубина без отвлечения.
const bloomDrift = keyframes`
  0%   { transform: translateX(-50%) translateY(0) scale(1); opacity: 0.5; }
  50%  { transform: translateX(-47%) translateY(1.5%) scale(1.06); opacity: 0.62; }
  100% { transform: translateX(-50%) translateY(0) scale(1); opacity: 0.5; }
`;

/**
 * Спокойная брендовая глубина страницы чата: статичный iris-mesh дизайн-системы
 * + мягкое верхнее свечение + тонкая сетка + нижняя виньетка. Декоративный, не
 * интерактивный. Без тяжёлой анимации — чат рабочая поверхность, и сильное
 * движение фона отвлекало бы (в отличие от лендинга).
 */
function ChatBackdrop() {
  return (
    <Box position="absolute" inset={0} pointerEvents="none" zIndex={0} overflow="hidden">
      {/* Статичный iris/cyan/magenta mesh дизайн-системы (приглушён, верхний акцент). */}
      <Box
        position="absolute"
        inset={0}
        bgImage={gradients.midnightMesh}
        opacity={0.32}
        sx={{ maskImage: 'radial-gradient(120% 90% at 50% -10%, #000 45%, transparent 100%)' }}
      />
      {/* Мягкое верхнее свечение. */}
      <Box
        position="absolute"
        top="-20%"
        left="50%"
        w="min(900px, 80%)"
        h="55%"
        transform="translateX(-50%)"
        bgImage={gradients.bloomHero}
        opacity={0.5}
        filter="blur(30px)"
        sx={{
          '@media (prefers-reduced-motion: no-preference)': {
            animation: `${bloomDrift} 34s ease-in-out infinite`,
          },
          '@media (max-width: 640px)': { animation: 'none' },
        }}
      />
      {/* Тонкая iris-сетка с радиальной маской. */}
      <Box
        position="absolute"
        inset={0}
        backgroundImage="linear-gradient(rgba(140,160,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(140,160,255,0.03) 1px, transparent 1px)"
        backgroundSize="48px 48px"
        opacity={0.4}
        sx={{ maskImage: 'radial-gradient(80% 70% at 50% 30%, #000 0%, transparent 80%)' }}
      />
      {/* Нижняя виньетка — глубина под лентой сообщений. */}
      <Box
        position="absolute"
        inset={0}
        bg="linear-gradient(180deg, transparent 0%, rgba(3,4,9,0.35) 60%, rgba(3,4,9,0.7) 100%)"
      />
    </Box>
  );
}

// Пропсов нет: при стриминге родитель ре-рендерится на каждый токен, а фон
// статичен — memo снимает лишний рендер декоративного слоя.
export default memo(ChatBackdrop);
