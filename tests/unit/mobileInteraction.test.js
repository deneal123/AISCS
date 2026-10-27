import theme from '../../src/theme';
import { MOBILE_EDITABLE_FIELDS, MOBILE_FIELD_QUERY, TOUCH_GESTURE_QUERY } from '../../src/theme/mobileInteraction';
import { typography } from '../../src/theme/tokens';

it('owns coarse-pointer gesture policy in the real global theme without disabling panning', () => {
  const styles = theme.styles.global({ theme, colorMode: 'dark' });
  expect(styles[TOUCH_GESTURE_QUERY]['*'].touchAction).toBe('pan-x pan-y');
  expect(styles.body.touchAction).toBeUndefined();
  expect(styles['*']?.touchAction).toBeUndefined();
});

it('uses the canonical field type scale for mobile text editing, including portalled inputs', () => {
  const styles = theme.styles.global({ theme, colorMode: 'dark' });
  expect(styles[MOBILE_FIELD_QUERY][MOBILE_EDITABLE_FIELDS].fontSize).toBe(`${typography.scale.fs[16]} !important`);
  for (const type of ['text', 'email', 'password', 'search', 'number']) {
    expect(MOBILE_EDITABLE_FIELDS).toContain(`input[type="${type}"]`);
  }
  expect(MOBILE_EDITABLE_FIELDS).toContain('textarea');
  expect(MOBILE_EDITABLE_FIELDS).not.toContain('checkbox');
  expect(MOBILE_EDITABLE_FIELDS).not.toContain('range');
});
