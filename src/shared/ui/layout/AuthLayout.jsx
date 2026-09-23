import React from "react";
import { Box } from "@chakra-ui/react";
import { Outlet } from "react-router-dom";
import { colors } from "@theme/tokens";
import { ScrollToTop } from "@shared/ui/atoms";
import FinsBackground from "@shared/visual/FinsBackground";
import Footer from "./Footer";

/**
 * Минимальный лейаут для входа/регистрации: без общего sticky-хедера и без
 * зажатого центрирования. Сцена авторизации занимает целый фолд (100svh) и
 * скроллится (не обрезается), а футер идёт ПОД фолдом — виден только прокруткой
 * (претензия #4). Сам AuthPageShell рисует фон/витрину/форму внутри сцены.
 */
function AuthLayout() {
  return (
    <Box
      position="relative"
      bg={colors.background.darkPrimary}
      w="100%"
      minH="100svh"
      display="flex"
      flexDirection="column"
    >
      <ScrollToTop />

      {/* Фон-«рёбра» InCellCorp на всю сцену (fixed, вне трансформа — работает).
          На reduced/off — лёгкий CSS-фолбэк; консистентно с лендингом. */}
      <FinsBackground />

      {/* Сцена авторизации — целый фолд, скроллится при нехватке высоты */}
      <Box
        as="main"
        position="relative"
        zIndex={1}
        flex="1"
        display="flex"
        flexDirection="column"
        minH="100svh"
      >
        <Outlet />
      </Box>

      {/* Футер под фолдом */}
      <Box position="relative" zIndex={1}>
        <Footer />
      </Box>
    </Box>
  );
}

export default AuthLayout;
