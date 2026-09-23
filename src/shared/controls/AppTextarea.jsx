import React, { forwardRef } from 'react';
import { Textarea } from '@chakra-ui/react';

/** Shared textarea owner: resize is deliberately disabled across product UI. */
const AppTextarea = forwardRef(function AppTextarea({ sx, resize: _resize, ...props }, ref) {
  void _resize;
  return (
    <Textarea
      ref={ref}
      className="resize-none"
      resize="none"
      sx={{ ...sx, resize: 'none' }}
      {...props}
    />
  );
});

export default AppTextarea;
