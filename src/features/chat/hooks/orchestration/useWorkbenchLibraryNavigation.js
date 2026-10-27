import { useCallback, useEffect, useRef, useState } from 'react';

/** Library is a peer overlay, never a surface transition or a workspace action. */
export function useWorkbenchLibraryNavigation({ pathname, ensureWorkMounted, sidebar }) {
  const [path, setPath] = useState(null);
  const finalFocusRef = useRef(null);
  const currentPath = useRef(pathname);
  const currentSidebar = useRef(sidebar);
  const mounted = useRef(false);
  currentPath.current = pathname;
  currentSidebar.current = sidebar;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const open = useCallback((event) => {
    if (!mounted.current || currentPath.current !== pathname) return;
    finalFocusRef.current = currentSidebar.current?.isOpen
      ? document.querySelector('button[aria-label="Меню"]') : event?.currentTarget;
    ensureWorkMounted(); setPath(pathname); currentSidebar.current?.onClose?.();
  }, [ensureWorkMounted, pathname]);
  const close = useCallback(() => {
    if (mounted.current && currentPath.current === pathname) setPath(null);
  }, [pathname]);
  // Mask an old route immediately. Initial thread hydration in the same URL
  // must not dismiss a Library the user has just explicitly opened.
  useEffect(() => { setPath((current) => current === pathname ? current : null); }, [pathname]);
  return { open, workProps: { libraryOpen: path === pathname,
    libraryReturnFocus: finalFocusRef, onLibraryClose: close } };
}
