import React from "react";
import { Box, keyframes } from "@chakra-ui/react";
import { Outlet, useLocation } from "react-router-dom";
import Header from "./Header";
import SkipLink from "./SkipLink";
import Footer from "./Footer";
import { LayoutProvider } from "@app/providers";
import { gradients, colors, spacing } from "@theme/tokens";
import { ScrollToTop } from "@shared/ui/atoms";
import { isChatRoute } from "@app/router/routes";

// CSS animation for page transitions - works on iOS Safari
const fadeIn = keyframes`
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
`;

function ProtectedLayout() {
  const location = useLocation();
  const [layoutVariant, setLayoutVariant] = React.useState("container");
  const [isFooterVisible, setFooterVisible] = React.useState(true);

  const isChat = isChatRoute(location.pathname);
  const effectiveVariant = isChat ? "full" : layoutVariant;
  const effectiveFooter = isChat ? false : isFooterVisible;


  return (
    <LayoutProvider state={{ variant: effectiveVariant, isFooterVisible: effectiveFooter }} actions={{ setVariant: setLayoutVariant, setFooterVisible }}>
      <Box position="relative" bg={colors.background.darkPrimary} w="100%" minH="100vh" display="flex" flexDirection="column">
        <ScrollToTop />

        {/* Background layers - pointer-events: none is critical! */}
        <Box
          position="fixed"
          top={0}
          left={0}
          right={0}
          bottom={0}
          bg={gradients.midnightMesh}
          opacity={0.55}
          pointerEvents="none"
          zIndex={0}
        />
        <Box
          position="fixed"
          top={0}
          left={0}
          right={0}
          bottom={0}
          bg="linear-gradient(180deg, rgba(5,5,5,0.95), rgba(5,5,5,0.8))"
          pointerEvents="none"
          zIndex={0}
        />

        <SkipLink />

        {/* Header */}
        <Header />

        {/* Main content - uses CSS animation instead of framer-motion */}
        <Box
          as="main"
          id="main"
          position="relative"
          zIndex={1}
          key={location.pathname}
          flex="1"
          minH={0}
          display="flex"
          flexDirection="column"
          animation={`${fadeIn} 0.25s ease-out forwards`}
          sx={{ "@media (prefers-reduced-motion: reduce)": { animation: "none" } }}
        >
          {effectiveVariant === "full" ? (
            <Outlet />
          ) : (
            // flex="1 0 auto" + minH="100svh" — растёт с контентом И заполняет
            // фолд; футер уходит под фолд (претензия #4). НЕ flex="1" (basis 0%
            // ломает высокий контент — контент переполняет и налезает на футер).
            <Box
              maxW="6xl"
              mx="auto"
              w="100%"
              flex="1 0 auto"
              minH="100svh"
              display="flex"
              flexDirection="column"
              px={{ base: spacing.md, md: spacing.lg, lg: spacing[13] }}
              py={{ base: 8, md: 10 }}
            >
              <Outlet />
            </Box>
          )}
        </Box>

        {/* Footer */}
        {effectiveFooter && (
          <Box position="relative" zIndex={1}>
            <Footer />
          </Box>
        )}
      </Box>
    </LayoutProvider>
  );
}

export default ProtectedLayout;
