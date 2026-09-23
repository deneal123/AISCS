/**
 * Design System Tokens
 * Centralized design constants for TeleRAG platform
 * Based on provided design specification
 */

export const colors = {
  // Text colors
  text: {
    primary: "#ffffff",
    primaryInverted: "#050505",
    secondary: "rgba(255, 255, 255, 0.75)",
    tertiary: "rgba(255, 255, 255, 0.5)",
    quaternary: "rgba(255, 255, 255, 0.25)",
  },

  // Background colors
  // Фон страницы = ink-1000 (#000), как --bg-page эталона. Был off-ramp #050505:
  // приподнятая база «съедала» контраст серого текста поверх живого фона.
  background: {
    darkPrimary: "#000000",
    darkPrimary75: "rgba(0, 0, 0, 0.75)",
    darkPrimary50: "rgba(0, 0, 0, 0.5)",
    darkPrimary25: "rgba(0, 0, 0, 0.25)",
    buttonActive: "#ffffff",
    buttonDisabled: "rgba(255, 255, 255, 0.5)",
    chineseBlack10: "rgba(16, 16, 16, 0.1)",
    chineseBlack50: "rgba(16, 16, 16, 0.5)",
    jet30: "rgba(53, 53, 53, 0.3)",
    jet40: "rgba(53, 53, 53, 0.4)",
    jet50: "rgba(53, 53, 53, 0.5)",
  },

  // Blur backgrounds
  blur: {
    dark: "rgba(21, 21, 21, 0.75)",
    mid: "rgba(53, 53, 53, 0.75)",
    medium: "rgba(30, 30, 30, 0.7)",
    light: "rgba(21, 21, 21, 0.5)",
    accent: "rgba(80, 80, 80, 0.75)",
  },

  // Border colors
  border: {
    default: "rgba(255, 255, 255, 0.05)",
    subtle: "rgba(255, 255, 255, 0.08)",
    medium: "rgba(255, 255, 255, 0.12)",
    light: "rgba(255, 255, 255, 0.15)",
  },

  scrollbar: {
    thumb: "rgba(140, 160, 255, 0.18)",
    thumbHover: "rgba(140, 160, 255, 0.30)",
    thumbActive: "rgba(140, 160, 255, 0.42)",
    track: "transparent",
  },

  // Brand accent colors — единственный сплошной акцент: электрический синий.
  brand: {
    primary: "#2D5BFF", // --blue-500 (InCellCorp PRIMARY)
    secondary: "#8b5cf6",
    tertiary: "#1dd1a1",
  },

  // Status colors — ТОЛЬКО для статусов (success/error/warning), не как бренд-акцент.
  success: "#10b981", // green
  error: "#ef4444", // red (только ошибки/danger) — ЕДИНЫЙ красный статуса
  warning: "#f59e0b", // orange
  info: "#60a5fa", // sky-blue — нейтральный инфо-статус (тосты, инфо-бейджи трейса)

  // Мягкие статус-тинты (фон/бордер чипов и бейджей) — единый источник вместо
  // разрозненных rgba(...) по компонентам.
  successSoft: "rgba(16,185,129,0.14)",
  successBorder: "rgba(16,185,129,0.30)",
  errorSoft: "rgba(239,68,68,0.15)",
  errorBorder: "rgba(239,68,68,0.35)",
  warningSoft: "rgba(245,158,11,0.14)",
  warningBorder: "rgba(245,158,11,0.30)",
  infoSoft: "rgba(96,165,250,0.14)",
  infoBorder: "rgba(96,165,250,0.30)",

  // ============ InCellCorp design language (02-tokens.md), JS-порт ============

  // Surface / neutral ramp (cool near-black -> white)
  ink: {
    1000: "#000000",
    950: "#030409",
    900: "#0A0C12",
    850: "#0E1119",
    800: "#131724",
    700: "#1A1E2C",
    600: "#232839",
    500: "#3A3F52",
    400: "#5C6376",
    300: "#8A90A2",
    200: "#B7BBC8",
    100: "#E4E6EC",
    0: "#FFFFFF",
  },

  // Primary — Electric blue
  blue: {
    50: "#E8EEFF",
    100: "#C7D3FF",
    300: "#6685FF",
    500: "#2D5BFF",
    600: "#1E47E6",
    700: "#1839BF",
    900: "#0A1A66",
  },

  // Accents — ТОЛЬКО в градиентах / glow / иридесценции, НИКОГДА как сплошная заливка.
  iris: { 300: "#9FB0FF", 500: "#5E7BFF", 700: "#3A4FD6" },
  cyan: { 300: "#7DF0DA", 500: "#3DD9BC", 700: "#1FA28A" },
  violet: { 300: "#B79DFF", 500: "#7C5BFF", 700: "#5237D6" },
  magenta: { 300: "#D69BFF", 500: "#B45CFF" },
  spectral: { pink: "#FF7AD9", amber: "#FFC56E" },

  // Semantic foreground (роль текста)
  fg: {
    1: "#FFFFFF", // headings / emphasis
    2: "#B7BBC8", // strong body
    3: "#8A90A2", // body
    // Small metadata must remain readable on the darkest translucent panels.
    // #737A8D keeps hierarchy below fg[3] while clearing the 4.5:1 AA floor.
    4: "#737A8D", // meta / labels
    disabled: "#3A3F52",
  },

  // Semantic background
  bg: {
    page: "#000000",
    section: "#030409",
    card: "#0A0C12",
    card2: "#0E1119",
    overlay: "rgba(8, 10, 16, 0.72)",
    // Тёмные подложки инпутов/хрома — единый источник (INPUT_BASE, чат-сайдбар/шапка/липкий композер).
    input: "rgba(8, 10, 20, 0.55)",
    inputStrong: "rgba(8, 10, 20, 0.72)",
    chrome: "rgba(12, 15, 28, 0.72)",
    header: "rgba(8, 10, 18, 0.82)",
    sticky: "rgba(6, 8, 14, 0.92)",
    // Тонированная full-bleed панель (LandingWhy / ростер агентов /platform) — ритм-перебой.
    panel: "rgba(6, 8, 18, 0.55)",
  },

  // Accent semantic (синий)
  accent: {
    base: "#2D5BFF",
    hover: "#1E47E6",
    press: "#1839BF",
    soft: "rgba(45, 91, 255, 0.12)",
    glow: "rgba(45, 91, 255, 0.35)",
    // "Ghost button/badge" recipe — раньше был скопирован литералами в 7+ мест
    // (admin/billing панели): фон/бордер/hover одного и того же синего чипа.
    subtle: "rgba(45, 91, 255, 0.16)",
    subtleBorder: "rgba(45, 91, 255, 0.3)",
    subtleHover: "rgba(45, 91, 255, 0.24)",
    subtleText: "#93b4ff",
    // Инпут focus-ring (AuthInput/PasswordInput) — было продублировано литералом.
    focusRing: "rgba(45, 91, 255, 0.15)",
    // Синие hover/active/softest поверхности (чат-сайдбар, композер, месседж-айтем).
    hoverSoft: "rgba(45, 91, 255, 0.22)",
    pressSoft: "rgba(45, 91, 255, 0.28)",
    softest: "rgba(45, 91, 255, 0.06)",
  },

  // Glass / depth surface tokens
  glass: {
    bg: "rgba(16, 20, 38, 0.55)",
    bg2: "rgba(22, 28, 52, 0.62)",
    border: "rgba(140, 160, 255, 0.16)",
    borderHi: "rgba(140, 160, 255, 0.34)",
    blur: "14px",
    blurStrong: "22px",
    highlight: "inset 0 1px 0 rgba(255, 255, 255, 0.07)",
    // Ховер/актив стеклянных поверхностей — единый источник вместо
    // rgba(140,160,255,.08/.14) в StateCard/SegmentedControl/CHAT_THEME.
    hover: "rgba(140, 160, 255, 0.08)",
    active: "rgba(140, 160, 255, 0.14)",
  },

  // Colored card auras (top-anchored radial bloom)
  aura: {
    iris: "radial-gradient(60% 60% at 50% 0%, rgba(94, 123, 255, 0.22), transparent 70%)",
    cyan: "radial-gradient(60% 60% at 50% 0%, rgba(61, 217, 188, 0.16), transparent 70%)",
    magenta: "radial-gradient(60% 60% at 50% 0%, rgba(180, 92, 255, 0.18), transparent 70%)",
  },
};

// Доп. семантические бордеры InCellCorp (расширяем существующий border-объект).
colors.border.faint = "rgba(255, 255, 255, 0.04)";
colors.border.strong = "rgba(255, 255, 255, 0.14)";
colors.border.blue = "rgba(45, 91, 255, 0.45)";
// Кольцо фокуса — ОТДЕЛЬНАЯ роль, не border.blue: тот полупрозрачный (1.6:1 к
// фону) и годится как декоративная рамка, но как индикатор фокуса практически
// невидим. Непрозрачный blue[300] даёт 6.4:1 и проходит SC 2.4.11.
colors.border.focus = colors.blue[300];

// Непрозрачная поверхность «всплывающего хрома» — меню, тосты, поповеры.
// Раньше каждый писал свой почти-чёрный литерал (rgba(9,9,9,.96), (10,10,10,.97),
// (11,11,11,.98), (14,14,14,1)) — все НЕЙТРАЛЬНО-серые, вне холодной ink-рампы:
// рядом с синеватыми дроверами это было видно глазом. Значение = ink-рампа.
colors.bg.menu = "rgba(9, 12, 22, 0.97)";
colors.border.card = "rgba(102, 133, 255, 0.18)";
colors.border.icon = "rgba(45, 91, 255, 0.25)";
// Полу-прозрачная «волосяная» линия (коннекторы трейса) — 0.09 ≈ 0.08, сводим к subtle.
colors.border.hairline = "rgba(255, 255, 255, 0.09)";

// Палитра субагентов — ЕДИНЫЙ источник для чат-трейса (features/chat/utils/trace.js)
// и витрины /platform (content/platform.js). Ключ = id агента.
colors.agents = {
  router: "#94a3b8",
  general: "#60a5fa",
  web_search: "#34d399",
  deep_research: "#a78bfa",
  image_gen: "#f472b6",
  pptx_gen: "#fbbf24",
  audio_transcribe: "#22d3ee",
  multimodal: "#fb923c",
  planner: "#f87171",
};
// Фолбэк-палитра для неизвестных агентов (детерминированный хеш по индексу).
colors.agentPalette = [
  "#60a5fa", "#34d399", "#a78bfa", "#f472b6", "#fbbf24",
  "#22d3ee", "#fb923c", "#f87171", "#a3e635", "#e879f9",
];

// Белые-альфа поверхности/тинты (панели, ховеры, разделители) — заполняют
// разрыв ramp .04→.05→.08 без разрозненных rgba(255,255,255,α) по компонентам.
colors.surface = {
  tint1: "rgba(255, 255, 255, 0.02)",
  tint2: "rgba(255, 255, 255, 0.03)",
  tint3: "rgba(255, 255, 255, 0.06)",
};

export const typography = {
  fontFamily: {
    // InCellCorp: Inter — UI + display; JetBrains Mono — eyebrows/metrics/labels/code.
    // Оба шрифта уже подключены в public/index.html.
    primary: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    mono: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
    fallback: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif",
  },

  // Type scale / веса / line-height / tracking (03-typography.md)
  scale: {
    fs: {
      12: "12px", 13: "13px", 14: "14px", 15: "15px", 16: "16px",
      18: "18px", 20: "20px", 24: "24px", 30: "30px", 36: "36px",
      44: "44px", 56: "56px", 72: "72px", 88: "88px",
      displayFluid: "clamp(32px, 9vw, 88px)",
    },
    fw: { regular: 400, medium: 500, semibold: 600, bold: 700, black: 800 },
    lh: { display: 1.02, tight: 1.05, snug: 1.15, base: 1.5, loose: 1.65 },
    tracking: { display: "-0.02em", normal: "0" },
  },

  // Title styles
  title: {
    large: {
      fontSize: "30px",
      lineHeight: "115%",
      fontWeight: 500,
    },
    medium: {
      fontSize: "24px",
      lineHeight: "125%",
      fontWeight: 500,
    },
    small: {
      fontSize: "22px",
      lineHeight: "115%",
      fontWeight: 500,
    },
  },

  // Subtitle styles
  subtitle: {
    large: {
      fontSize: "20px",
      lineHeight: "125%",
      fontWeight: 500,
    },
    medium: {
      fontSize: "16px",
      lineHeight: "125%",
      fontWeight: 500,
    },
  },

  // Body text styles
  body: {
    large: {
      fontSize: "18px",
      lineHeight: "150%",
      fontWeight: 500,
    },
    medium: {
      fontSize: "14px",
      lineHeight: "140%",
      fontWeight: 500,
    },
  },

  // Footnote styles
  footnote: {
    medium: {
      fontSize: "14px",
      lineHeight: "107%",
      fontWeight: 500,
    },
    small: {
      fontSize: "12px",
      lineHeight: "125%",
      fontWeight: 500,
    },
  },
};

const spacingScale = [
  "0px", // 0
  "2px", // 1
  "4px", // 2
  "6px", // 3
  "8px", // 4
  "12px", // 5
  "16px", // 6
  "20px", // 7
  "24px", // 8
  "28px", // 9
  "32px", // 10
  "36px", // 11
  "40px", // 12
  "48px", // 13
  "56px", // 14
  "64px", // 15
  "72px", // 16
  "80px", // 17
  "96px", // 18
  "112px", // 19
  "128px", // 20
  "160px", // 21
];

const spacingAliases = {
  none: spacingScale[0],
  "3xs": spacingScale[1],
  "2xs": spacingScale[2],
  xs: spacingScale[3],
  sm: spacingScale[4],
  md: spacingScale[6],
  lg: spacingScale[8],
  xl: spacingScale[10],
  "2xl": spacingScale[12],
  "3xl": spacingScale[13],
  "4xl": spacingScale[14],
  "5xl": spacingScale[15],
  "6xl": spacingScale[16],
  "7xl": spacingScale[17],
  "8xl": spacingScale[18],
  "9xl": spacingScale[19],
  "10xl": spacingScale[20],
  "11xl": spacingScale[21],
};

export const spacing = Object.assign([...spacingScale], {
  scale: spacingScale,
  ...spacingAliases,
});

export const borderRadius = {
  sm: "10px",
  md: "15px",
  lg: "20px",
  xl: "25px",
  "2xl": "30px",
  full: "9999px",
};

export const borderWidth = {
  default: "1px",
  medium: "2px",
  thick: "3px",
};

export const blur = {
  strength: {
    default: "25px",
    light: "15px",
    heavy: "40px",
  },
};

export const shadows = {
  subtle: "0 1px 4px rgba(0, 0, 0, 0.12)",
  elevated: "0 12px 32px rgba(0, 0, 0, 0.32)",
  // Единственный сплошной акцент — синий: glow был фиолетовым (139,92,246),
  // выбивался из бренд-правила рядом с glowSubtle/glowAccent (оба синие).
  glow: "0 0 28px rgba(45, 91, 255, 0.55)",
  glowSubtle: "0 0 18px rgba(45, 91, 255, 0.25)",
  // InCellCorp depth / glow (02-tokens.md)
  glassCard:
    "0 1px 0 rgba(255,255,255,0.05) inset, 0 0 0 1px rgba(140,160,255,0.16), 0 10px 30px rgba(0,0,0,0.45)",
  glassLift:
    "0 1px 0 rgba(255,255,255,0.07) inset, 0 0 0 1px rgba(140,160,255,0.34), 0 24px 60px rgba(0,0,0,0.55), 0 0 36px rgba(94,123,255,0.16)",
  modal: "0 24px 64px rgba(0,0,0,0.65), 0 0 0 1px rgba(255,255,255,0.08)",
  buttonPrimary:
    "inset 0 1px 0 rgba(255,255,255,0.22), 0 1px 0 rgba(0,0,0,0.4), 0 6px 20px rgba(45,91,255,0.40)",
  glowAccent: "0 0 0 1px rgba(45,91,255,0.55), 0 0 40px rgba(45,91,255,0.25)",
  glowIris: "0 0 0 1px rgba(94,123,255,0.50), 0 0 44px rgba(94,123,255,0.28)",
  // Оверлеи (меню/дровер) и мягкое «свечение» пользовательского пузыря — единый источник.
  menu: "0 20px 40px rgba(0,0,0,0.5)",
  drawer: "-20px 0 60px rgba(0,0,0,0.55)",
  glowUser: "0 2px 12px rgba(45,91,255,0.10)",
  // Свечение активной кнопки отправки (композер / actions месседжа) — 3× дубль сведён.
  sendGlow: "inset 0 1px 0 rgba(255,255,255,0.22), 0 4px 14px rgba(45,91,255,0.35)",
};

// Motion (easings + длительности) — 02-tokens.md
export const motion = {
  easeOut: "cubic-bezier(0.16, 1, 0.3, 1)",
  easeInOut: "cubic-bezier(0.65, 0, 0.35, 1)",
  durFast: "120ms",
  durBase: "200ms",
  durSlow: "360ms",
};

export const transitions = {
  default: "0.2s ease",
  smooth: "0.3s ease-in-out",
  slow: "0.5s ease",
};

export const gradients = {
  aurora:
    "linear-gradient(135deg, rgba(45, 91, 255, 0.9) 0%, rgba(58, 79, 214, 0.85) 45%, rgba(124, 91, 255, 0.95) 100%)",
  // primary button: blue -> iris (06-components.md)
  prism: "linear-gradient(135deg, #2D5BFF 0%, #5E7BFF 100%)",
  dusk: "linear-gradient(160deg, rgba(45, 91, 255, 0.15) 0%, rgba(94, 123, 255, 0.25) 65%, rgba(61, 217, 188, 0.15) 100%)",
  // Page/section mesh — синие/iris/cyan/magenta радиальные блобы (02-tokens.md).
  midnightMesh:
    "radial-gradient(40% 50% at 18% 22%, rgba(94, 123, 255, 0.30), transparent 60%), radial-gradient(45% 55% at 82% 18%, rgba(180, 92, 255, 0.20), transparent 62%), radial-gradient(50% 60% at 70% 88%, rgba(61, 217, 188, 0.16), transparent 64%), radial-gradient(60% 70% at 30% 80%, rgba(45, 91, 255, 0.18), transparent 66%)",
  meshHero:
    "radial-gradient(40% 50% at 18% 22%, rgba(94, 123, 255, 0.30), transparent 60%), radial-gradient(45% 55% at 82% 18%, rgba(180, 92, 255, 0.20), transparent 62%), radial-gradient(50% 60% at 70% 88%, rgba(61, 217, 188, 0.16), transparent 64%), radial-gradient(60% 70% at 30% 80%, rgba(45, 91, 255, 0.18), transparent 66%)",
  meshSection:
    "radial-gradient(50% 60% at 80% 0%, rgba(94, 123, 255, 0.12), transparent 60%), radial-gradient(40% 50% at 10% 100%, rgba(180, 92, 255, 0.08), transparent 62%)",
  // Тонированная секция — ритм-перебой (мягкий градиент вместо плоской заливки).
  sectionTint: "linear-gradient(180deg, rgba(20, 24, 52, 0.30), rgba(6, 8, 18, 0.04))",
  // Иридесцентный спектральный свет (hero title, top-line, accents).
  iridescent:
    "linear-gradient(105deg, #3DD9BC 0%, #5E7BFF 22%, #7C5BFF 40%, #B45CFF 58%, #FF7AD9 74%, #FFC56E 88%, #3DD9BC 100%)",
  // Hero glow (iris -> blue -> cyan, magenta edge).
  glow:
    "radial-gradient(ellipse at 50% 50%, rgba(94, 123, 255, 0.46) 0%, rgba(45, 91, 255, 0.30) 34%, rgba(61, 217, 188, 0.18) 62%, rgba(180, 92, 255, 0.10) 80%, rgba(0, 0, 0, 0) 100%)",
  border:
    "linear-gradient(135deg, rgba(94, 123, 255, 0.58) 0%, rgba(45, 91, 255, 0.55) 38%, rgba(61, 217, 188, 0.52) 72%, rgba(180, 92, 255, 0.50) 100%)",
  bloomHero:
    "radial-gradient(52% 44% at 50% 6%, rgba(94, 123, 255, 0.32), rgba(180, 92, 255, 0.14) 44%, transparent 72%)",
  // Радужная top-line для glass-карт (появляется на hover).
  cardTopLine:
    "linear-gradient(90deg, transparent, rgba(61,217,188,0.70), rgba(94,123,255,0.82), rgba(180,92,255,0.60), rgba(255,122,217,0.48), transparent)",
  // Gradient-число метрик (count-up): белый → blue[300].
  metricNumber: "linear-gradient(135deg, #FFFFFF 20%, #6685FF 100%)",
  // CTA-band: диагональная синяя→cyan заливка (_before) + белый скан-луч (_after, анимируется .cta-scan).
  ctaWash:
    "linear-gradient(100deg, transparent, rgba(45,91,255,0.20) 54%, rgba(61,217,188,0.16))",
  ctaScan:
    "linear-gradient(110deg, transparent 30%, rgba(255,255,255,0.12) 50%, transparent 70%)",
};

export const breakpoints = {
  mobile: "320px",
  tablet: "768px",
  desktop: "1024px",
  wide: "1280px",
};

export const dimensions = {
  iconButton: {
    width: "40px",
    height: "40px",
  },
  button: {
    heightMobile: "45px",
    heightDesktop: "50px",
  },
};

export const layers = {
  base: 0,
  sticky: 100,
  dropdown: 220,
  popover: 320,
  header: 420,
  backdrop: 520,
  dialog: 620,
  drawer: 720,
  command: 820,
  toast: 920,
};

// Default export as unified tokens object
export const tokens = {
  colors,
  typography,
  spacing,
  borderRadius,
  borderWidth,
  blur,
  shadows,
  transitions,
  motion,
  breakpoints,
  dimensions,
  layers,
  gradients,
};


export const chat = {
  // Селектор модели — ссылается на семантические токены (было 12 сырых rgba).
  modelSelector: {
    triggerBg: colors.border.faint, // .04
    triggerBgHover: colors.border.subtle, // .08
    triggerBorder: colors.border.strong, // .14
    triggerBorderActive: colors.border.blue, // .45 (было .46 — дрейф)
    triggerText: "rgba(255, 255, 255, 0.94)", // near-white текст — оставляем
    activeText: colors.blue[100], // #C7D3FF
    activeBg: colors.accent.subtle, // rgba(45,91,255,0.16)
    activeBgHover: colors.accent.hoverSoft, // rgba(45,91,255,0.22)
    menuBg: colors.bg.menu, // единая поверхность всплывающего хрома (ink-рампа)
    menuBorder: colors.border.strong, // .14
    itemHover: colors.surface.tint3, // .06
    itemSelectedBg: colors.accent.subtle,
  },
};
