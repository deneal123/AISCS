/**
 * useResponsive — хук для адаптивного дизайна
 * Предоставляет информацию о текущем размере экрана и breakpoints
 */

import { useState, useEffect, useMemo, useCallback } from "react";

// Breakpoints согласно Chakra UI (можно настроить)
const BREAKPOINTS = {
  base: 0,
  sm: 480,
  md: 768,
  lg: 992,
  xl: 1280,
  "2xl": 1536,
};

/**
 * Хук для определения текущего breakpoint
 * @returns {Object} Объект с информацией о текущем breakpoint
 */
export function useResponsive() {
  const [windowSize, setWindowSize] = useState({
    width: typeof window !== "undefined" ? window.innerWidth : 0,
    height: typeof window !== "undefined" ? window.innerHeight : 0,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;

    let timeoutId = null;
    let lastRunAt = 0;

    const updateWindowSize = () => {
      setWindowSize((prev) => {
        const next = {
          width: window.innerWidth,
          height: window.innerHeight,
        };
        if (prev.width === next.width && prev.height === next.height) {
          return prev;
        }
        return next;
      });
      lastRunAt = Date.now();
    };

    const handleResize = () => {
      const now = Date.now();
      const remaining = 120 - (now - lastRunAt);
      if (remaining <= 0) {
        if (timeoutId) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        updateWindowSize();
        return;
      }
      if (!timeoutId) {
        timeoutId = setTimeout(() => {
          timeoutId = null;
          updateWindowSize();
        }, remaining);
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, []);

  const breakpoint = useMemo(() => {
    const { width } = windowSize;
    if (width >= BREAKPOINTS["2xl"]) return "2xl";
    if (width >= BREAKPOINTS.xl) return "xl";
    if (width >= BREAKPOINTS.lg) return "lg";
    if (width >= BREAKPOINTS.md) return "md";
    if (width >= BREAKPOINTS.sm) return "sm";
    return "base";
  }, [windowSize]);

  const isMobile = useMemo(() => windowSize.width < BREAKPOINTS.md, [windowSize.width]);

  const isTablet = useMemo(
    () => windowSize.width >= BREAKPOINTS.md && windowSize.width < BREAKPOINTS.lg,
    [windowSize.width],
  );

  const isDesktop = useMemo(() => windowSize.width >= BREAKPOINTS.lg, [windowSize.width]);

  const isLandscape = useMemo(() => windowSize.width > windowSize.height, [windowSize]);

  return {
    windowSize,
    breakpoint,
    isMobile,
    isTablet,
    isDesktop,
    isLandscape,
    // Утилитарные функции
    isBreakpoint: useCallback((bp) => breakpoint === bp, [breakpoint]),
    isBreakpointUp: useCallback((bp) => windowSize.width >= BREAKPOINTS[bp], [windowSize.width]),
    isBreakpointDown: useCallback((bp) => windowSize.width < BREAKPOINTS[bp], [windowSize.width]),
  };
}

export default useResponsive;
