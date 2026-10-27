import { createContext, useContext, useEffect, useId, useState } from 'react';
import { Box, Tooltip } from '@chakra-ui/react';
import { colors, layers } from '@theme/tokens';

const HintOwner = createContext(null);

/** A choice surface owns one transient explanation, never a stack of tooltips. */
export function ChoiceHints({ children }) {
  const [active, setActive] = useState(null);
  useEffect(() => {
    if (active === null) return undefined;
    const dismiss = () => setActive(null);
    // Scroll does not bubble. Capture also covers nested listboxes and page scroll,
    // so an off-screen row cannot keep a portalled hint pinned to the viewport edge.
    window.addEventListener('scroll', dismiss, true);
    window.addEventListener('resize', dismiss);
    return () => {
      window.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('resize', dismiss);
    };
  }, [active]);
  return <HintOwner.Provider value={{ active, setActive }}>
    <Box onMouseLeave={() => setActive(null)} onWheelCapture={() => setActive(null)} onKeyDownCapture={(event) => {
      if (event.key === 'Escape') setActive(null);
    }}>{children}</Box>
  </HintOwner.Provider>;
}

export default function ChoiceHint({ children, label, keyboardOpen = false, renderTrigger, ...props }) {
  const id = useId();
  const shared = useContext(HintOwner);
  const [local, setLocal] = useState(null);
  const { active, setActive } = shared || { active: local, setActive: setLocal };
  const dismiss = () => setActive(previous => previous === id ? null : previous);
  useEffect(() => {
    if (keyboardOpen) setActive(id);
    else setActive(previous => previous === id ? null : previous);
  }, [keyboardOpen, id, setActive]);
  const triggerProps = { ...props, onMouseEnter: () => setActive(id), onMouseLeave: dismiss,
    onFocusCapture: () => setActive(id), onBlurCapture: dismiss, onClickCapture: dismiss };
  return <Tooltip label={label} isOpen={Boolean(label) && active === id}
    placement="top" hasArrow={false} openDelay={0} closeDelay={0}
    motionProps={{ variants: { enter: { opacity: 1, transition: { duration: 0 } }, exit: { opacity: 0, transition: { duration: 0 } } } }}
    bg={colors.bg.menu} color={colors.fg[2]} border="1px solid" borderColor={colors.border.strong}
    maxW="220px" fontSize="11px" lineHeight={1.4} px={2} py={1.5} zIndex={layers.tooltip}>
    {renderTrigger ? renderTrigger(triggerProps) : <Box minW={0} {...triggerProps}>{children}</Box>}
  </Tooltip>;
}
