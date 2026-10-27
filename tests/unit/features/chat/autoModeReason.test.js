import { autoModeReasonLabel } from '../../../../src/features/chat/utils/autoModeReason';

describe('auto-mode reason labels', () => {
  it.each(['constructor', 'toString', '__proto__', 'PRIVATE_REASON', null, undefined])(
    'unknown reason %s is neutral, never inherited or rendered raw', (reason) => {
      expect(autoModeReasonLabel(reason)).toBe('Решение принято по правилам авто-режима.');
    },
  );
});
