import React, { forwardRef, useCallback, useLayoutEffect, useRef } from 'react';
import { Textarea, useMergeRefs } from '@chakra-ui/react';
import { observeResizeFrame } from '../utils/observeResizeFrame';

/** Shared textarea owner: resize is deliberately disabled across product UI. */
const AppTextarea = forwardRef(function AppTextarea({ sx, resize: _resize, autoGrow = false,
  maxAutoHeight = 360, onInput, rows, ...props }, ref) {
  void _resize;
  const element = useRef(null);
  const mergedRef = useMergeRefs(element, ref);
  const fit = useCallback(() => {
    if (!autoGrow || !element.current) return;
    const input = element.current;
    input.style.height = 'auto';
    if (input.scrollHeight) input.style.height = `${Math.min(maxAutoHeight, input.scrollHeight)}px`;
    input.style.overflowY = input.scrollHeight > maxAutoHeight ? 'auto' : 'hidden';
  }, [autoGrow, maxAutoHeight]);
  useLayoutEffect(fit, [fit, props.value]);
  useLayoutEffect(() => {
    if (!autoGrow || !element.current || typeof ResizeObserver === 'undefined') return undefined;
    const input = element.current;
    let width = input.offsetWidth;
    return observeResizeFrame(input, () => {
      // Own height/scrollbar changes must not be mistaken for parent resizing.
      if (input.offsetWidth === width) return;
      width = input.offsetWidth;
      fit();
    }, { box: 'border-box' });
  }, [autoGrow, fit]);
  return (
    <Textarea
      ref={mergedRef}
      rows={rows ?? (autoGrow ? 1 : undefined)}
      onInput={(event) => { fit(); onInput?.(event); }}
      className="resize-none"
      resize="none"
      sx={{ ...sx, resize: 'none' }}
      {...props}
    />
  );
});

export default AppTextarea;
