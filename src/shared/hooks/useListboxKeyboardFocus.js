import { useEffect, useRef, useState } from 'react';

/** Style virtual option focus without changing the listbox library's focus owner. */
export function useListboxKeyboardFocus(enabled) {
  const ref = useRef(null);
  const keyboard = useRef(false);
  const [visible, setVisible] = useState(false);
  const pointer = () => { keyboard.current = false; setVisible(false); };
  useEffect(() => {
    if (!enabled) return undefined;
    const onKey = (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      keyboard.current = true;
      if (ref.current?.contains(document.activeElement)) setVisible(true);
    };
    const onPointer = () => { keyboard.current = false; setVisible(false); };
    // Tab may originate in the overlay header, outside this listbox.
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('pointerdown', onPointer, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('pointerdown', onPointer, true);
    };
  }, [enabled]);
  return { visible: enabled && visible, props: {
    ref,
    onFocusCapture: () => setVisible(keyboard.current),
    onBlurCapture: event => { if (!event.currentTarget.contains(event.relatedTarget)) setVisible(false); },
    onPointerMoveCapture: pointer,
    onPointerDownCapture: pointer,
  } };
}
