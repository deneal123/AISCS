import { useMediaQuery } from '@chakra-ui/react';

const MEDIUM_QUERY = '(min-width: 768px)';
const WIDE_QUERY = '(min-width: 1200px)';

/**
 * Workbench breakpoints are part of the Work Hub interaction contract rather
 * than aliases for the application-wide responsive scale.
 */
export function useWorkbenchLayout() {
  const [isMedium, isWide] = useMediaQuery([MEDIUM_QUERY, WIDE_QUERY], {
    ssr: false,
    fallback: false,
  });

  if (isWide) return 'wide';
  if (isMedium) return 'medium';
  return 'mobile';
}
