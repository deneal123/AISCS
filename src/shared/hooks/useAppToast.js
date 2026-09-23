import React from 'react';
import { Box, Icon, Text, useToast } from '@chakra-ui/react';
import { FiAlertCircle, FiAlertTriangle, FiCheckCircle, FiInfo, FiX } from '@shared/icons';
import { borderRadius, colors, shadows } from '@theme/tokens';

// Статус-палитра — из семантических токенов (было параллельным форком
// #4ade80/#f87171/#fbbf24/#60a5fa). Единый источник success/error/warning/info.
const STATUS_CONFIG = {
  success: { icon: FiCheckCircle, color: colors.success, border: colors.successBorder, bg: colors.successSoft },
  error: { icon: FiAlertCircle, color: colors.error, border: colors.errorBorder, bg: colors.errorSoft },
  warning: { icon: FiAlertTriangle, color: colors.warning, border: colors.warningBorder, bg: colors.warningSoft },
  info: { icon: FiInfo, color: colors.info, border: colors.infoBorder, bg: colors.infoSoft },
};

const MOBILE_TOAST_MAX_WIDTH = 'calc(100vw - 32px)';
const MOBILE_TOAST_BREAKPOINT = 768;
const TOAST_DEDUP_WINDOW_MS = 2000;
const DESKTOP_STACK_LIMIT = 3;
const MOBILE_STACK_LIMIT = 1;
const TOAST_BASE_CONTAINER_STYLE = {
  width: `min(360px, ${MOBILE_TOAST_MAX_WIDTH})`,
  minWidth: 0,
  maxWidth: MOBILE_TOAST_MAX_WIDTH,
};
const DESKTOP_TOAST_CONTAINER_STYLE = {
  ...TOAST_BASE_CONTAINER_STYLE,
  // Keep confirmations above the persistent composer/editor action shelf.
  // The toast remains transient and never owns recovery instructions.
  margin: '0 16px 88px',
};
const MOBILE_TOAST_CONTAINER_STYLE = {
  ...TOAST_BASE_CONTAINER_STYLE,
  // Clear the mobile editor/composer action shelf, the toast entrance motion,
  // and the device safe area so feedback never hides the available actions.
  margin: '0 16px calc(112px + env(safe-area-inset-bottom, 0px))',
};

function resolveToastLayout() {
  const mobile = typeof window !== 'undefined' && window.innerWidth < MOBILE_TOAST_BREAKPOINT;
  return mobile
    ? { position: 'bottom', containerStyle: MOBILE_TOAST_CONTAINER_STYLE }
    : { position: 'bottom-right', containerStyle: DESKTOP_TOAST_CONTAINER_STYLE };
}

function stableToastId({ id, operationId, title, status }) {
  if (id != null) return String(id);
  if (operationId) return `operation:${operationId}`;
  const source = `${status || 'info'}:${title || 'notice'}`;
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `app-toast:${(hash >>> 0).toString(36)}`;
}

function AppToast({ title, description, status = 'info', onClose }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.info;
  return (
    <Box
      display="flex"
      alignItems="flex-start"
      gap={3}
      px={4}
      py={3}
      borderRadius={borderRadius.md}
      bg={colors.bg.menu}
      border="1px solid"
      borderColor={cfg.border}
      boxShadow={`${shadows.menu}, 0 0 0 1px ${cfg.border}`}
      w="100%"
      minW={0}
      maxW="360px"
      position="relative"
      sx={{ background: `linear-gradient(135deg, ${colors.bg.menu} 0%, ${cfg.bg} 100%)` }}
    >
      <Box pt="1px" flexShrink={0}>
        <Icon as={cfg.icon} boxSize="16px" color={cfg.color} aria-hidden />
      </Box>
      <Box flex="1" minW={0}>
        {title && (
          <Text fontSize="13px" fontWeight="600" color={colors.fg[1]} lineHeight="1.4">
            {title}
          </Text>
        )}
        {description && (
          <Text fontSize="12px" color={colors.fg[3]} mt={title ? 0.5 : 0} lineHeight="1.5">
            {description}
          </Text>
        )}
      </Box>
      {onClose && (
        <Box
          as="button"
          aria-label="Закрыть уведомление"
          onClick={onClose}
          flexShrink={0}
          color={colors.fg[4]}
          _hover={{ color: colors.fg[2] }}
          pt="2px"
          cursor="pointer"
        >
          <Icon as={FiX} boxSize="13px" aria-hidden />
        </Box>
      )}
    </Box>
  );
}

export function useAppToast() {
  const toast = useToast();
  const recentRef = React.useRef(new Map());
  const visibleRef = React.useRef([]);

  return React.useCallback((options = {}) => {
    const {
      title,
      description,
      status = 'info',
      duration = status === 'error' ? null : 3500,
      isClosable = true,
      operationId,
      onCloseComplete,
      ...rest
    } = options;
    const layout = resolveToastLayout();
    const id = stableToastId({ id: options.id, operationId, title, status });
    const now = Date.now();
    const previous = recentRef.current.get(id) || 0;
    const payload = {
      id,
      duration,
      isClosable,
      // Chakra animates right-positioned toast wrappers along the X axis.
      // On narrow screens that temporary transform extends the fixed portal
      // beyond the viewport even when the rendered card itself is narrower.
      // The centered bottom placement uses a Y-axis transition instead.
      position: layout.position,
      containerStyle: layout.containerStyle,
      ...rest,
      onCloseComplete: () => {
        visibleRef.current = visibleRef.current.filter((current) => current !== id);
        recentRef.current.delete(id);
        onCloseComplete?.();
      },
      render: ({ onClose }) => (
        <AppToast
          title={title}
          description={description}
          status={status}
          onClose={isClosable ? onClose : undefined}
        />
      ),
    };

    recentRef.current.set(id, now);
    if (previous && now - previous <= TOAST_DEDUP_WINDOW_MS && toast.isActive?.(id)) {
      toast.update?.(id, payload);
      return id;
    }

    const limit = layout.position === 'bottom' ? MOBILE_STACK_LIMIT : DESKTOP_STACK_LIMIT;
    visibleRef.current = visibleRef.current.filter((current) => toast.isActive?.(current));
    while (visibleRef.current.length >= limit) {
      const oldest = visibleRef.current.shift();
      if (oldest) toast.close?.(oldest);
    }
    visibleRef.current.push(id);
    toast(payload);
    return id;
  }, [toast]);
}
