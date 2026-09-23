import React, { forwardRef } from 'react';
import { Box, Link, useStyleConfig } from '@chakra-ui/react';
import { Link as RouterLink } from 'react-router-dom';
import { colors } from '@theme/tokens';

/**
 * Navigation with the visual language of a Chakra Button and the semantics of
 * a real link. Actions must keep using Button; navigation must use this owner.
 */
const ActionLink = forwardRef(function ActionLink({
  to,
  href,
  children,
  leftIcon,
  rightIcon,
  variant = 'primary',
  size = 'md',
  colorScheme,
  isExternal = false,
  ...props
}, ref) {
  const styles = useStyleConfig('Button', { variant, size, colorScheme });
  const navigation = to ? { as: RouterLink, to } : { href, isExternal };

  return (
    <Link
      ref={ref}
      {...navigation}
      __css={styles}
      display="inline-flex"
      alignItems="center"
      justifyContent="center"
      gap={2}
      textDecoration="none"
      cursor="pointer"
      _hover={{ ...styles?._hover, textDecoration: 'none' }}
      _focusVisible={{
        ...styles?._focusVisible,
        outline: '2px solid',
        outlineColor: colors.border.focus,
        outlineOffset: '2px',
      }}
      {...props}
    >
      {leftIcon && <Box as="span" display="inline-flex" aria-hidden>{leftIcon}</Box>}
      <Box as="span" minW={0}>{children}</Box>
      {rightIcon && <Box as="span" display="inline-flex" aria-hidden>{rightIcon}</Box>}
    </Link>
  );
});

export default ActionLink;
