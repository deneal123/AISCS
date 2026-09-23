import { notifyBillingRefresh } from '@features/billing/context/BillingContext';

describe('billing context helpers', () => {
  it('notifyBillingRefresh dispatches a billing:refresh window event', () => {
    const handler = jest.fn();
    window.addEventListener('billing:refresh', handler);
    try {
      notifyBillingRefresh();
      expect(handler).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('billing:refresh', handler);
    }
  });
});
