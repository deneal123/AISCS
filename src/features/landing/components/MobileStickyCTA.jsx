import React, { useEffect, useState } from "react";
import { Box, HStack } from "@chakra-ui/react";
import { useAuth } from "@app/providers";
import { GLASS_SURFACE_STRONG } from "@theme/glass";
import ActionLink from "@shared/controls/ActionLink";

/**
 * Плавающая CTA-плашка внизу на мобилке (конверсия гостя). Появляется после
 * прокрутки ~0.72×vh, только гостю, только ≤lg. Учитывает safe-area, тач ≥48px.
 * Порт рецепта docs/design_transfer/06 (MobileStickyCTA).
 */
export default function MobileStickyCTA() {
  const { isAuthenticated } = useAuth();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (isAuthenticated) return undefined;
    const onScroll = () => {
      setVisible(window.scrollY > window.innerHeight * 0.72);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [isAuthenticated]);

  if (isAuthenticated) return null;

  return (
    <Box
      display={{ base: "block", lg: "none" }}
      position="fixed"
      left={0}
      right={0}
      bottom={0}
      zIndex={90}
      px={4}
      pt={3}
      pb="calc(env(safe-area-inset-bottom, 0px) + 12px)"
      pointerEvents={visible ? "auto" : "none"}
      visibility={visible ? "visible" : "hidden"}
      opacity={visible ? 1 : 0}
      transform={visible ? "translateY(0)" : "translateY(16px)"}
      transition="opacity 260ms cubic-bezier(0.16,1,0.3,1), transform 260ms cubic-bezier(0.16,1,0.3,1)"
      sx={{ "@media (prefers-reduced-motion: reduce)": { transition: "opacity 0.01ms" } }}
    >
      <HStack
        {...GLASS_SURFACE_STRONG}
        spacing={2.5}
        p={2}
        borderRadius="16px"
      >
        <ActionLink to="/signup" variant="primary" size="md" flex="1" minH="48px">
          Начать бесплатно
        </ActionLink>
        <ActionLink to="/login" variant="secondary" size="md" minH="48px" px={5}>
          Войти
        </ActionLink>
      </HStack>
    </Box>
  );
}
