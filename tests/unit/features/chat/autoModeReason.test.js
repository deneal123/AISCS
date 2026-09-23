import { autoModeReasonLabel } from '../../../../src/features/chat/utils/autoModeReason';

describe('auto-mode trace reasons', () => {
  it('renders a safe label for a known policy code', () => {
    expect(autoModeReasonLabel('confirmation_required')).toBe('Дорогой режим ждёт подтверждения.');
  });

  it('does not render an unknown producer value', () => {
    expect(autoModeReasonLabel('synthetic-model-rationale-must-not-render')).toBe(
      'Решение принято по правилам авто-режима.'
    );
  });
});
