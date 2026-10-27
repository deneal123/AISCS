import { typography } from './tokens';

export const TOUCH_GESTURE_QUERY = '@media (hover: none) and (pointer: coarse)';
export const MOBILE_FIELD_QUERY = '@media (max-width: 767px), (hover: none) and (pointer: coarse)';

// Keep non-text controls (file, range, checkbox, radio, buttons) untouched.
export const MOBILE_EDITABLE_FIELDS = [
  'input:not([type])',
  ...['text', 'email', 'password', 'search', 'tel', 'url', 'number', 'date', 'time', 'datetime-local', 'month', 'week']
    .map((type) => `input[type="${type}"]`),
  'textarea', 'select', '[contenteditable="true"]', '[contenteditable="plaintext-only"]',
].join(', ');

/** Touch gestures do not own browser-menu/keyboard zoom or system accessibility. */
export const MOBILE_INTERACTION_STYLES = {
  [TOUCH_GESTURE_QUERY]: {
    // Apply to nested scrollers and portalled sheets, not only the document root.
    '*': { touchAction: 'pan-x pan-y' },
  },
  [MOBILE_FIELD_QUERY]: {
    // A global mobile field rule intentionally wins compact component/SDK styles.
    [MOBILE_EDITABLE_FIELDS]: { fontSize: `${typography.scale.fs[16]} !important` },
  },
};
