/**
 * Кастомный icon-сет GPTHub — единый источник вместо react-icons (Feather/Fa).
 *
 * Зачем: генеричные Feather-иконки не читались как «наш» бренд. Это собственный
 * набор в едином языке — сетка 24, штрих 1.75, currentColor, скруглённые
 * соединения с чуть более «острым» геометрическим характером; фирменная
 * «электрическая» молния (FiZap) — тот же угловатый мотив, что у фона/орбиты.
 *
 * API совместим с react-icons: компонент принимает те же пропсы, работает и
 * напрямую `<FiZap/>`, и как `<Icon as={FiZap} boxSize=.. color=../>` (Chakra).
 * Размер = 1em (наследует font-size / boxSize), цвет = currentColor.
 *
 * Имена совпадают со старыми (Fi.. / Fa..), поэтому замена — только смена импорта:
 *   from react-icons -> from @shared/icons
 */
import React from "react";

// База: fill/stroke заданы ПОСЛЕ {...p}, чтобы победить возможный fill=currentColor
// от Chakra `Icon as=`; width/height/aria — ДО {...p}, чтобы вызывающий мог их
// переопределить (boxSize через className, aria-label).
const Ico = ({ children, ...p }) => (
  <svg
    viewBox="0 0 24 24"
    width="1em"
    height="1em"
    aria-hidden="true"
    focusable="false"
    {...p}
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {children}
  </svg>
);

/* ── Бренд / энергия ─────────────────────────────────────────────────────── */
// Фирменная «электрическая» молния — угловатая, тот же язык, что у орбиты/фона.
export const FiZap = (p) => (
  <Ico {...p}><path d="M13 2 4 13.5h6.2L11 22l9-11.5h-6.2L15 2Z" /></Ico>
);
export const FiActivity = (p) => (
  <Ico {...p}><path d="M22 12h-4l-3 8-6-16-3 8H2" /></Ico>
);
export const FiAward = (p) => (
  <Ico {...p}><circle cx="12" cy="8" r="5" /><path d="M8.2 12.5 7 22l5-3 5 3-1.2-9.5" /></Ico>
);
export const FiStar = (p) => (
  <Ico {...p}><path d="m12 3 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5-5.8-3.1-5.8 3.1 1.1-6.5L2.6 9.8l6.5-.9L12 3Z" /></Ico>
);
export const FiCompass = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="m15.6 8.4-2 5.2-5.2 2 2-5.2 5.2-2Z" /></Ico>
);

/* ── Агенты / возможности ────────────────────────────────────────────────── */
export const FiMessageSquare = (p) => (
  <Ico {...p}><path d="M21 4H3v13h5v4l5-4h8V4Z" /></Ico>
);
export const FiMessageCircle = (p) => (
  <Ico {...p}><path d="M21 11.5a8.5 8.5 0 0 1-12.3 7.6L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z" /></Ico>
);
export const FiGlobe = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="M2.5 12h19M12 2.5c2.6 2.6 4 6 4 9.5s-1.4 6.9-4 9.5c-2.6-2.6-4-6-4-9.5s1.4-6.9 4-9.5Z" /></Ico>
);
export const FiSearch = (p) => (
  <Ico {...p}><circle cx="10.5" cy="10.5" r="7" /><path d="m20 20-4.4-4.4" /></Ico>
);
export const FiImage = (p) => (
  <Ico {...p}><rect x="3" y="3" width="18" height="18" rx="2.5" /><circle cx="8.5" cy="8.5" r="1.8" /><path d="m4 17 5-5 4 4 3-3 4 4" /></Ico>
);
export const FiFile = (p) => (
  <Ico {...p}><path d="M14 3H6v18h12V7l-4-4Z" /><path d="M14 3v4h4" /></Ico>
);
export const FiFileText = (p) => (
  <Ico {...p}><path d="M14 3H6v18h12V7l-4-4Z" /><path d="M14 3v4h4M9 12h6M9 16h6M9 8h2" /></Ico>
);
export const FiFolder = (p) => (
  <Ico {...p}><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2.5h9A1.5 1.5 0 0 1 21 9v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18V6.5Z" /></Ico>
);
export const FiDatabase = (p) => (
  <Ico {...p}><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></Ico>
);
export const FiArchive = (p) => (
  <Ico {...p}><rect x="3" y="3.5" width="18" height="4.5" rx="1" /><path d="M5 8v12h14V8M9.5 12h5" /></Ico>
);
export const FiMic = (p) => (
  <Ico {...p}><rect x="9" y="2.5" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" /></Ico>
);
export const FiHeadphones = (p) => (
  <Ico {...p}><path d="M4 13v-1a8 8 0 0 1 16 0v1" /><rect x="2.5" y="13" width="4.5" height="7" rx="1.6" /><rect x="17" y="13" width="4.5" height="7" rx="1.6" /></Ico>
);
export const FiCode = (p) => (
  <Ico {...p}><path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16" /></Ico>
);
export const FiCpu = (p) => (
  <Ico {...p}><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="9.5" y="9.5" width="5" height="5" rx="1" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></Ico>
);
export const FiServer = (p) => (
  <Ico {...p}><rect x="3" y="4" width="18" height="7" rx="1.6" /><rect x="3" y="13" width="18" height="7" rx="1.6" /><path d="M7 7.5h.01M7 16.5h.01" /></Ico>
);
export const FiGitBranch = (p) => (
  <Ico {...p}><circle cx="7" cy="5" r="2.5" /><circle cx="7" cy="19" r="2.5" /><circle cx="17" cy="8" r="2.5" /><path d="M7 7.5v9M17 10.5c0 4-4 4.5-7 5" /></Ico>
);
export const FiGitMerge = (p) => (
  <Ico {...p}><circle cx="7" cy="6" r="2.5" /><circle cx="7" cy="18" r="2.5" /><circle cx="17" cy="12" r="2.5" /><path d="M7 8.5v7M7 11c0 3 3.4 3.5 7.5 3.5" /></Ico>
);
export const FiLayers = (p) => (
  <Ico {...p}><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 13 9 5 9-5M3 16.5l9 5 9-5" /></Ico>
);
export const FiTool = (p) => (
  <Ico {...p}><path d="M14.5 6a4 4 0 0 1 5 5l-2-.5-2.5 2.5.5 2a4 4 0 0 1-5-5l2 .5L15 8l-.5-2Z" /><path d="m12 12-7 7" /></Ico>
);
export const FiPaperclip = (p) => (
  <Ico {...p}><path d="M20 11.5 12 19.5a5 5 0 0 1-7-7l8-8a3.3 3.3 0 0 1 4.7 4.7l-8 8a1.7 1.7 0 0 1-2.4-2.4l7.2-7.2" /></Ico>
);

/* ── Действия / стрелки ──────────────────────────────────────────────────── */
export const FiArrowRight = (p) => (
  <Ico {...p}><path d="M4 12h15M13 6l6 6-6 6" /></Ico>
);
export const FiArrowDown = (p) => (
  <Ico {...p}><path d="M12 4v15M6 13l6 6 6-6" /></Ico>
);
export const FiArrowUpRight = (p) => (
  <Ico {...p}><path d="M7 17 17 7M8 7h9v9" /></Ico>
);
export const FiArrowDownRight = (p) => (
  <Ico {...p}><path d="M7 7l10 10M17 8v9H8" /></Ico>
);
export const FiChevronDown = (p) => (
  <Ico {...p}><path d="m6 9 6 6 6-6" /></Ico>
);
export const FiChevronUp = (p) => (
  <Ico {...p}><path d="m6 15 6-6 6 6" /></Ico>
);
export const FiChevronLeft = (p) => (
  <Ico {...p}><path d="m15 6-6 6 6 6" /></Ico>
);
export const FiChevronRight = (p) => (
  <Ico {...p}><path d="m9 6 6 6-6 6" /></Ico>
);
export const FiCornerDownLeft = (p) => (
  <Ico {...p}><path d="M20 5v6a3 3 0 0 1-3 3H5M9 10l-4 4 4 4" /></Ico>
);
export const FiSend = (p) => (
  <Ico {...p}><path d="M21 3 3 10.5l7 2.5 2.5 7L21 3Z" /><path d="M10 13.5 21 3" /></Ico>
);
export const FiShare2 = (p) => (
  <Ico {...p}><circle cx="18" cy="5" r="2.6" /><circle cx="6" cy="12" r="2.6" /><circle cx="18" cy="19" r="2.6" /><path d="m8.3 10.8 7.4-4.3M8.3 13.2l7.4 4.3" /></Ico>
);
export const FiExternalLink = (p) => (
  <Ico {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5H5V6h5" /></Ico>
);
export const FiDownload = (p) => (
  <Ico {...p}><path d="M12 3v12M7 10l5 5 5-5M4 20h16" /></Ico>
);
export const FiRefreshCw = (p) => (
  <Ico {...p}><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16M3 12a9 9 0 0 1 15.5-6.3L21 8" /><path d="M21 3v5h-5M3 21v-5h5" /></Ico>
);
export const FiRepeat = (p) => (
  <Ico {...p}><path d="M17 2.5 21 6.5 17 10.5M3 11V9a3 3 0 0 1 3-3h15M7 21.5 3 17.5 7 13.5M21 13v2a3 3 0 0 1-3 3H3" /></Ico>
);
export const FiRotateCcw = (p) => (
  <Ico {...p}><path d="M3 4v5h5" /><path d="M3.5 9a8.5 8.5 0 1 1-1.7 5" /></Ico>
);

/* ── Статусы / знаки ─────────────────────────────────────────────────────── */
export const FiCheck = (p) => (
  <Ico {...p}><path d="m5 12.5 4.5 4.5L19 7" /></Ico>
);
export const FiCheckCircle = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="m8 12.2 2.8 2.8L16.5 9" /></Ico>
);
export const FiPlus = (p) => (
  <Ico {...p}><path d="M12 5v14M5 12h14" /></Ico>
);
export const FiPlusCircle = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="M12 8v8M8 12h8" /></Ico>
);
export const FiCircle = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9" /></Ico>
);
export const FiSquare = (p) => (
  <Ico {...p}><rect x="4" y="4" width="16" height="16" rx="2.5" /></Ico>
);
export const FiInfo = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="M12 11v5M12 7.6h.01" /></Ico>
);
export const FiAlertCircle = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="M12 7.5v6M12 16.4h.01" /></Ico>
);
export const FiAlertTriangle = (p) => (
  <Ico {...p}><path d="M12 3.5 22 20H2L12 3.5Z" /><path d="M12 9.5v4.5M12 17.2h.01" /></Ico>
);
export const FiThumbsUp = (p) => (
  <Ico {...p}><path d="M7 10v11H4V10h3Z" /><path d="M7 10.5 11.5 3a2 2 0 0 1 2 2v4H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 21H7" /></Ico>
);
export const FiThumbsDown = (p) => (
  <Ico {...p}><path d="M17 14V3h3v11h-3Z" /><path d="M17 13.5 12.5 21a2 2 0 0 1-2-2v-4H5a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.2 3H17" /></Ico>
);

/* ── Навигация / хром ───────────────────────────────────────────────────── */
export const FiMenu = (p) => (
  <Ico {...p}><path d="M3 6h18M3 12h18M3 18h18" /></Ico>
);
export const FiSettings = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2.5v3M12 18.5v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2.5 12h3M18.5 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></Ico>
);
export const FiSliders = (p) => (
  <Ico {...p}><path d="M4 21v-6M4 11V3M12 21v-8M12 9V3M20 21v-4M20 13V3M1.5 15h5M9.5 9h5M17.5 17h5" /></Ico>
);
export const FiSearch2 = FiSearch;
export const FiX = (p) => (
  <Ico {...p}><path d="M6 6l12 12M18 6 6 18" /></Ico>
);
export const FiMoreHorizontal = (p) => (
  <Ico {...p}><path d="M5 12h.01M12 12h.01M19 12h.01" /></Ico>
);

/* ── Данные / графики ────────────────────────────────────────────────────── */
export const FiBarChart2 = (p) => (
  <Ico {...p}><path d="M6 20v-7M12 20V4M18 20v-11M3 20h18" /></Ico>
);
export const FiPieChart = (p) => (
  <Ico {...p}><path d="M21 12a9 9 0 1 1-9-9v9h9Z" /><path d="M14 3.3A9 9 0 0 1 20.7 10H14V3.3Z" /></Ico>
);
export const FiTrendingUp = (p) => (
  <Ico {...p}><path d="M3 17 10 10l4 4 7-7" /><path d="M15 7h6v6" /></Ico>
);
export const FiTrendingDown = (p) => (
  <Ico {...p}><path d="M3 7 10 14l4-4 7 7" /><path d="M15 17h6v-6" /></Ico>
);
export const FiPercent = (p) => (
  <Ico {...p}><path d="m19 5-14 14" /><circle cx="7.5" cy="7.5" r="2.5" /><circle cx="16.5" cy="16.5" r="2.5" /></Ico>
);
export const FiClock = (p) => (
  <Ico {...p}><circle cx="12" cy="12" r="9.5" /><path d="M12 7v5.2l3.5 2.1" /></Ico>
);
export const FiCalendar = (p) => (
  <Ico {...p}><rect x="3.5" y="5" width="17" height="16" rx="2" /><path d="M3.5 9.5h17M8 3v4M16 3v4" /></Ico>
);

/* ── Пользователь / аккаунт ─────────────────────────────────────────────── */
export const FiUser = (p) => (
  <Ico {...p}><circle cx="12" cy="8" r="4" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" /></Ico>
);
export const FiUsers = (p) => (
  <Ico {...p}><circle cx="9" cy="8" r="3.6" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.6a3.6 3.6 0 0 1 0 6.8M17.5 14.2A6.5 6.5 0 0 1 21.5 20" /></Ico>
);
export const FiLogOut = (p) => (
  <Ico {...p}><path d="M15 4H5v16h10" /><path d="M10 12h11M17 8l4 4-4 4" /></Ico>
);
export const FiKey = (p) => (
  <Ico {...p}><circle cx="8" cy="15" r="4.5" /><path d="m11 12 8-8M16 7l2.5 2.5M14 9l2.5 2.5" /></Ico>
);
export const FiLock = (p) => (
  <Ico {...p}><rect x="4.5" y="10.5" width="15" height="10" rx="2" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" /></Ico>
);
export const FiShield = (p) => (
  <Ico {...p}><path d="M12 2.5 20 6v6c0 5-3.5 8-8 9.5C7.5 20 4 17 4 12V6l8-3.5Z" /></Ico>
);
export const FiEye = (p) => (
  <Ico {...p}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></Ico>
);

/* ── Разное / коммуникации ──────────────────────────────────────────────── */
export const FiMail = (p) => (
  <Ico {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3.5 6.5 8.5 6 8.5-6" /></Ico>
);
export const FiPhone = (p) => (
  <Ico {...p}><path d="M6 3H9l1.5 5-2 1.5a11 11 0 0 0 5 5l1.5-2 5 1.5V21a2 2 0 0 1-2.2 2A18 18 0 0 1 3 5.2 2 2 0 0 1 6 3Z" /></Ico>
);
export const FiMapPin = (p) => (
  <Ico {...p}><path d="M12 22c5-5 8-8.5 8-12a8 8 0 1 0-16 0c0 3.5 3 7 8 12Z" /><circle cx="12" cy="10" r="3" /></Ico>
);
export const FiCloud = (p) => (
  <Ico {...p}><path d="M7 19a5 5 0 0 1-.6-9.96A6 6 0 0 1 18 8.5 4.5 4.5 0 0 1 17.5 19H7Z" /></Ico>
);
export const FiInbox = (p) => (
  <Ico {...p}><path d="M3 13 6 4h12l3 9v7H3v-7Z" /><path d="M3 13h5l1.5 3h5L16 13h5" /></Ico>
);
export const FiTag = (p) => (
  <Ico {...p}><path d="M3 3h8l10 10-8 8L3 11V3Z" /><circle cx="7.5" cy="7.5" r="1.4" /></Ico>
);
export const FiBookOpen = (p) => (
  <Ico {...p}><path d="M12 5.5C10.5 4.2 8 3.5 3 3.5v14c5 0 7.5.7 9 2M12 5.5c1.5-1.3 4-2 9-2v14c-5 0-7.5.7-9 2M12 5.5v13.5" /></Ico>
);
export const FiCreditCard = (p) => (
  <Ico {...p}><rect x="2.5" y="5" width="19" height="14" rx="2.2" /><path d="M2.5 9.5h19M6 15h4" /></Ico>
);
export const FiCopy = (p) => (
  <Ico {...p}><rect x="8.5" y="8.5" width="12" height="12" rx="2" /><path d="M4.5 15.5H4a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 .5.5v.5" /></Ico>
);
export const FiEdit2 = (p) => (
  <Ico {...p}><path d="M16.5 4.5 19.5 7.5 8 19l-4 1 1-4L16.5 4.5Z" /></Ico>
);
export const FiEdit3 = (p) => (
  <Ico {...p}><path d="M12 20h9" /><path d="M16.5 3.5 20.5 7.5 8 20l-4 1 1-4L16.5 3.5Z" /></Ico>
);
export const FiTrash2 = (p) => (
  <Ico {...p}><path d="M4 6h16M9 6V3.5h6V6M6 6l1 15h10l1-15M10 10.5v6M14 10.5v6" /></Ico>
);

/* ── Fa-совместимость (те же имена, что использовались из react-icons/fa) ── */
export const FaCheckCircle = FiCheckCircle;
export const FaExclamationCircle = FiAlertCircle;
export const FaRegClipboard = (p) => (
  <Ico {...p}><rect x="6" y="4.5" width="12" height="17" rx="2" /><rect x="9" y="2.5" width="6" height="3.5" rx="1" /></Ico>
);
export const FaSignInAlt = (p) => (
  <Ico {...p}><path d="M11 3h8v18h-8" /><path d="M3 12h11M10 8l4 4-4 4" /></Ico>
);
export const FaSignOutAlt = FiLogOut;
export const FaUser = FiUser;
export const FaUserPlus = (p) => (
  <Ico {...p}><circle cx="9" cy="8" r="3.8" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M18 8v6M15 11h6" /></Ico>
);
