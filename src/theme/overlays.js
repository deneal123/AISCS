// Chakra retains focus/portal ownership. Only shared viewport/scroll geometry changes.
const viewport = {
  h: 'var(--app-visual-height, 100dvh)',
  top: 'var(--app-visual-top, 0px)',
};

export const modalViewportTheme = {
  baseStyle: {
    dialogContainer: viewport,
    dialog: {
      maxH: 'calc(var(--app-visual-height, 100dvh) - 32px - env(safe-area-inset-top, 0px) - var(--app-safe-bottom, 0px))',
      overflowY: 'auto',
    },
    header: { flexShrink: 0 },
    body: { minH: 0, overscrollBehavior: 'contain' },
    footer: { flexShrink: 0, gap: '8px', flexWrap: 'wrap' },
  },
};

export const drawerViewportTheme = {
  baseStyle: {
    dialogContainer: viewport,
    dialog: { maxH: 'var(--app-visual-height, 100dvh)' },
    header: { flexShrink: 0 },
    body: {
      minH: 0, overscrollBehavior: 'contain',
      '&:last-child': { paddingBottom: 'calc(16px + var(--app-safe-bottom, 0px))' },
    },
    footer: { flexShrink: 0, paddingBottom: 'calc(12px + var(--app-safe-bottom, 0px))' },
  },
};
