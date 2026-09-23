import { request } from './request';

export const getBalance = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/billing/balance', signal });

export const getPacks = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/billing/packs', signal });

export const getUsageAnalytics = (range = '30d', { signal } = {}) =>
  request({
    method: 'get',
    url: `/api/billing/analytics?range=${encodeURIComponent(range)}`,
    signal,
  });

// Страница истории операций: { events, total, limit, offset }.
// `kind` — категория фильтра (usage/topup/subscription/refund); 'all' = без фильтра.
export const getBillingHistory = ({ limit, offset, kind, signal } = {}) => {
  const params = new URLSearchParams();
  if (limit != null) params.set('limit', String(limit));
  if (offset != null) params.set('offset', String(offset));
  if (kind && kind !== 'all') params.set('kind', kind);
  const query = params.toString();
  return request({
    method: 'get',
    url: `/api/billing/history${query ? `?${query}` : ''}`,
    signal,
  });
};

export const createCheckout = (payload, { signal } = {}) =>
  request({ method: 'post', url: '/api/billing/checkout', data: payload, signal });
