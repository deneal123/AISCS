import { extendTheme } from "@chakra-ui/react";
import {
  colors,
  typography,
  borderRadius,
  shadows,
  spacing,
  transitions,
  gradients,
  layers,
} from "./theme/tokens";

const brandPalette = {
  50: "#eef6ff",
  100: "#d9eaff",
  200: "#b6d4ff",
  300: "#8fbcff",
  400: "#5f99ff",
  500: colors.brand.primary,
  600: "#1E47E6",
  700: "#1839BF",
  800: "#153e96",
  900: "#0A1A66",
};

const chakraSpace = spacing.scale.reduce((acc, value, index) => {
  acc[index] = value;
  return acc;
}, {});

const theme = extendTheme({
  config: {
    initialColorMode: "dark",
    useSystemColorMode: false,
  },
  space: chakraSpace,
  fonts: {
    body: typography.fontFamily.primary,
    heading: typography.fontFamily.primary,
  },
  radii: {
    none: 0,
    sm: borderRadius.sm,
    md: borderRadius.md,
    lg: borderRadius.lg,
    xl: borderRadius.xl,
    "2xl": borderRadius["2xl"],
    card: borderRadius.md,
  },
  sizes: {
    container: {
      md: "48rem",
      lg: "62rem",
      xl: "75rem",
      "2xl": "88rem",
    },
  },
  zIndices: {
    base: layers.base,
    sticky: layers.sticky,
    dropdown: layers.dropdown,
    popover: layers.popover,
    overlay: layers.backdrop,
    modal: layers.dialog,
    drawer: layers.drawer,
    toast: layers.toast,
  },
  // Типо-роли (opt-in через textStyle="…") — единый источник иерархии вместо
  // инлайновых fontSize по компонентам. Аддитивно: без defaultProps ничего не
  // меняется, пока компонент явно не выберет роль.
  textStyles: {
    // Шкала выровнена под incellcorp (colors_and_type.css): смелее и крупнее.
    display: {
      fontSize: { base: "36px", sm: "48px", md: "60px", lg: "76px" },
      fontWeight: 800,
      lineHeight: 1.02,
      letterSpacing: "-0.02em",
    },
    // Правило эталона: отрицательный tracking ТОЛЬКО у display. Секционные
    // заголовки идут с 0 (их SectionHeader ставит "0" явно) — у нас был дрейф.
    title: {
      fontSize: { base: "28px", sm: "34px", md: "44px", lg: "48px" },
      fontWeight: 800,
      lineHeight: 1.05,
      letterSpacing: "0",
    },
    titleLg: {
      fontSize: { base: "32px", sm: "40px", md: "52px", lg: "56px" },
      fontWeight: 800,
      lineHeight: 1.04,
      letterSpacing: "0",
    },
    titleSm: {
      fontSize: { base: "21px", md: "26px" },
      fontWeight: 700,
      lineHeight: 1.2,
      letterSpacing: "0",
    },
    lede: {
      fontSize: { base: "16px", md: "19px" },
      fontWeight: 400,
      lineHeight: 1.6,
      color: colors.fg[3],
    },
    eyebrow: {
      fontFamily: typography.fontFamily.mono,
      fontSize: "12px",
      fontWeight: 600,
      letterSpacing: "0.14em",
      textTransform: "uppercase",
      color: colors.fg[4],
    },
    dataLabel: {
      fontFamily: typography.fontFamily.mono,
      fontSize: "10.5px",
      fontWeight: 600,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: colors.fg[4],
    },
    metric: {
      fontSize: { base: "34px", md: "46px" },
      fontWeight: 800,
      lineHeight: 1,
      letterSpacing: "-0.02em",
      fontVariantNumeric: "tabular-nums",
    },
    caption: {
      fontSize: "12px",
      fontWeight: 500,
      lineHeight: 1.5,
      color: colors.fg[4],
    },
    body: {
      fontSize: { base: "15px", md: "16px" },
      fontWeight: 400,
      lineHeight: 1.65,
      color: colors.fg[3],
    },
  },
  shadows: {
    elevated: shadows.elevated,
    subtle: shadows.subtle,
    glow: shadows.glow,
    glowSubtle: shadows.glowSubtle,
  },
  styles: {
    global: () => ({
      body: {
        bg: colors.background.darkPrimary,
        color: colors.text.primary,
        fontFamily: typography.fontFamily.primary,
      },
      "*, *::before, *::after": {
        borderColor: colors.border.default,
        scrollbarWidth: "thin",
        scrollbarColor: `${colors.scrollbar.thumb} ${colors.scrollbar.track}`,
      },
      "::selection": {
        backgroundColor: `${colors.brand.primary}55`,
        color: colors.text.primaryInverted,
      },
      // Синее focus-кольцо (единственный сплошной акцент). Берём border.focus
      // (blue[300], 6.4:1): brand.primary как обводка на чёрном даёт лишь 4:1 и
      // расходился с правилом в motion.css.
      "*:focus-visible": {
        outline: `2px solid ${colors.border.focus}`,
        outlineOffset: "2px",
      },
      // Тонкий скроллбар в бренд-палитре.
      "::-webkit-scrollbar": { width: "10px", height: "10px" },
      "::-webkit-scrollbar-track": { background: colors.scrollbar.track },
      "::-webkit-scrollbar-thumb": {
        background: colors.scrollbar.thumb,
        borderRadius: "8px",
      },
      "::-webkit-scrollbar-thumb:hover": { background: colors.scrollbar.thumbHover },
      "::-webkit-scrollbar-thumb:active": { background: colors.scrollbar.thumbActive },
      "@media (forced-colors: active)": {
        "*, *::before, *::after": {
          scrollbarColor: "ButtonText Canvas",
        },
        "*:focus-visible": {
          outlineColor: "Highlight",
        },
      },
      // Reduced-motion killswitch — гасит CSS-анимации/переходы глобально.
      "@media (prefers-reduced-motion: reduce)": {
        "*, *::before, *::after": {
          animationDuration: "0.001ms !important",
          animationIterationCount: "1 !important",
          transitionDuration: "0.001ms !important",
          scrollBehavior: "auto !important",
        },
      },
      // Перф на мобиле (≤640px): отключаем backdrop-blur (дорогой на GPU).
      // Поверхности остаются полупрозрачными за счёт glass-fill — стекло «читается»,
      // но без размытия (10-accessibility.md / styles.css home).
      "@media (max-width: 640px)": {
        "*, *::before, *::after": {
          backdropFilter: "none !important",
          WebkitBackdropFilter: "none !important",
        },
      },
      "@keyframes gradientOrbit": {
        "0%": { transform: "rotate(0deg)" },
        "100%": { transform: "rotate(360deg)" },
      },
      "@keyframes glowPulse": {
        "0%": { opacity: 0.4 },
        "50%": { opacity: 0.9 },
        "100%": { opacity: 0.4 },
      },
      "@keyframes shimmerTrail": {
        "0%": { transform: "translateX(-20%)" },
        "100%": { transform: "translateX(120%)" },
      },
    }),
  },
  components: {
    Tooltip: {
      baseStyle: {
        background: colors.blur.dark,
        color: colors.text.primary,
        borderRadius: borderRadius.sm,
        px: spacing.sm,
        py: spacing[4],
        fontSize: "12px",
      },
    },
    Button: {
      baseStyle: {
        fontWeight: 500,
        borderRadius: borderRadius.sm,
        transition: transitions.smooth,
        position: "relative",
        overflow: "hidden",
        letterSpacing: "0.02em",
      },
      variants: {
        // Оба варианта — pill (999px) и вес 700, как ВСЕ кнопки эталона.
        // Радиус/вес заданы на варианте, а не в baseStyle: иначе задело бы
        // ghost/solid и иконочные кнопки чата и админки.
        primary: {
          bgGradient: gradients.prism,
          color: colors.text.primary,
          boxShadow: shadows.buttonPrimary,
          border: "1px solid",
          borderColor: "rgba(140,160,255,0.5)",
          borderRadius: borderRadius.full,
          fontWeight: 700,
          lineHeight: 1,
          // Фирменный медленный sheen: у эталона он на КАЖДОЙ primary-кнопке
          // (у нас был только по классу .hero-pill на hero/CTA).
          _after: {
            content: '""',
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(110deg, transparent 0%, rgba(255,255,255,0.20) 42%, transparent 72%)",
            transform: "translateX(-120%)",
            animation: "button-sheen 7.2s ease-in-out infinite",
            borderRadius: "inherit",
            pointerEvents: "none",
          },
          _hover: {
            transform: "translateY(-1px)",
            borderColor: "rgba(125,240,218,0.5)",
            boxShadow: `${shadows.buttonPrimary}, ${shadows.glowIris}`,
          },
          _active: { transform: "translateY(0)", boxShadow: shadows.buttonPrimary },
          _disabled: {
            bg: colors.background.buttonDisabled,
            color: colors.text.quaternary,
            boxShadow: "none",
            opacity: 0.55,
          },
        },
        secondary: {
          // Чистый нейтральный ghost эталона. Был dusk-градиент в `_before`
          // (сине-бирюзовая заливка) — он делал вторичную кнопку «цветной».
          color: colors.fg[2],
          border: "1px solid",
          borderColor: colors.border.subtle,
          background: "rgba(255,255,255,0.035)",
          borderRadius: borderRadius.full,
          fontWeight: 700,
          lineHeight: 1,
          _hover: {
            transform: "translateY(-1px)",
            borderColor: "rgba(102,133,255,0.38)",
            background: "rgba(255,255,255,0.06)",
            boxShadow: "0 0 20px rgba(45,91,255,0.10)",
          },
          _active: { transform: "translateY(0)" },
          _disabled: {
            color: colors.text.quaternary,
            borderColor: colors.border.light,
            opacity: 0.55,
          },
        },
      },
    },
    Link: {
      baseStyle: {
        color: colors.text.secondary,
        transition: transitions.default,
        _hover: { color: colors.text.primary },
      },
    },
    Menu: {
      baseStyle: {
        list: {
          bg: colors.background.darkPrimary,
          border: "1px solid",
          borderColor: colors.border.medium,
          boxShadow: `0 20px 40px rgba(0, 0, 0, 0.5), 0 0 30px ${colors.accent.focusRing}`,
          py: 0,
          borderRadius: borderRadius.lg,
          overflow: "hidden",
        },
        item: {
          bg: "transparent",
          color: colors.text.primary,
          _hover: {
            bg: colors.accent.soft,
          },
          _focus: {
            bg: colors.accent.soft,
          },
        },
        divider: {
          borderColor: colors.border.subtle,
        },
      },
    },
  },
  colors: {
    brand: brandPalette,
    text: colors.text,
    background: colors.background,
    blur: colors.blur,
    border: colors.border,
    success: colors.success,
    error: colors.error,
    warning: colors.warning,
  },
  semanticTokens: {
    colors: {
      // Updated with design system tokens
      canvas: { default: "#f7f7f7", _dark: colors.background.darkPrimary },
      surface: { default: "white", _dark: colors.blur.dark },
      surfaceElevated: { default: "white", _dark: colors.blur.mid },
      borderSubtle: { default: "rgba(0,0,0,0.08)", _dark: colors.border.default },
      text: {
        primary: { default: "gray.800", _dark: colors.text.primary },
        muted: { default: "gray.600", _dark: colors.text.secondary },
        tertiary: { default: "gray.500", _dark: colors.text.tertiary },
      },
      accent: { default: "blue.600", _dark: colors.brand.primary },
    },
  },
});

export default theme;
