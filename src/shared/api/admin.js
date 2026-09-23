import { request } from './request';

// --- настройки ---
export const getAdminSettings = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/admin/settings', signal });

export const putAdminSetting = (key, value, { signal } = {}) =>
  request({ method: 'put', url: '/api/admin/settings', data: { key, value }, signal });

export const resetAdminSetting = (key, { signal } = {}) =>
  request({ method: 'delete', url: `/api/admin/settings/${encodeURIComponent(key)}`, signal });

// --- тарифы / цены (pricing — на billing-admin роутере) ---
export const getAdminPlans = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/admin/plans', signal });

export const getAdminPricing = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/admin/billing/pricing', signal });

export const putAdminPricing = (payload, { signal } = {}) =>
  request({ method: 'put', url: '/api/admin/billing/pricing', data: payload, signal });

export const getAdminReconcile = (range = '30d', { signal } = {}) =>
  request({ method: 'get', url: `/api/admin/billing/reconcile?range=${encodeURIComponent(range)}`, signal });

// Удаление цены модели (возврат к fallback). model_id содержит «/», поэтому идёт в path как есть.
export const deleteAdminPricing = (modelId, provider = '', { signal } = {}) => {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : '';
  return request({ method: 'delete', url: `/api/admin/billing/pricing/${modelId}${query}`, signal });
};

// Доступные модели (для автокомплита model_id в форме цен). Отдаёт агрегированный каталог.
export const getAvailableModels = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/chats/models', signal });

// --- пользователи ---
export const getAdminUsers = (query = '', { limit, offset, signal } = {}) => {
  const params = new URLSearchParams();
  if (query) params.set('query', query);
  if (limit != null) params.set('limit', String(limit));
  if (offset != null) params.set('offset', String(offset));
  const qs = params.toString();
  return request({ method: 'get', url: `/api/admin/users${qs ? `?${qs}` : ''}`, signal });
};

export const getAdminUser = (userId, { signal } = {}) =>
  request({ method: 'get', url: `/api/admin/users/${encodeURIComponent(userId)}`, signal });

// История операций пользователя (billing_events) с пагинацией limit/offset.
export const getUserEvents = (userId, { limit, offset, signal } = {}) => {
  const params = new URLSearchParams();
  if (limit != null) params.set('limit', String(limit));
  if (offset != null) params.set('offset', String(offset));
  const qs = params.toString();
  return request({
    method: 'get',
    url: `/api/admin/users/${encodeURIComponent(userId)}/events${qs ? `?${qs}` : ''}`,
    signal,
  });
};

export const adjustUserCredits = (userId, delta, reason, { signal } = {}) =>
  request({
    method: 'post',
    url: `/api/admin/users/${encodeURIComponent(userId)}/adjust-credits`,
    data: { delta, reason },
    signal,
  });

export const setUserRole = (userId, isAdmin, { signal } = {}) =>
  request({
    method: 'post',
    url: `/api/admin/users/${encodeURIComponent(userId)}/set-role`,
    data: { is_admin: isAdmin },
    signal,
  });

export const setUserActive = (userId, isActive, { signal } = {}) =>
  request({
    method: 'post',
    url: `/api/admin/users/${encodeURIComponent(userId)}/set-active`,
    data: { is_active: isActive },
    signal,
  });

export const setUserPlan = (userId, plan, { signal } = {}) =>
  request({
    method: 'post',
    url: `/api/admin/users/${encodeURIComponent(userId)}/set-plan`,
    data: { plan },
    signal,
  });

export const setUserBalance = (userId, balance, reason, { signal } = {}) =>
  request({
    method: 'post',
    url: `/api/admin/users/${encodeURIComponent(userId)}/set-balance`,
    data: { balance, reason },
    signal,
  });

// --- аналитика ---
export const getAdminAnalytics = (range = '30d', { signal } = {}) =>
  request({ method: 'get', url: `/api/admin/analytics?range=${encodeURIComponent(range)}`, signal });

// Последний снимок статуса провайдеров (без живой пробы — не тормозит панель).
export const getProvidersHealth = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/admin/providers/health', signal });

// Живая проверка всех провайдеров по кнопке: недостижимые → блок (скрыты у юзеров, не
// пробуются), снова достижимые → разблок. Возвращает свежий снимок.
export const recheckProvidersHealth = ({ signal } = {}) =>
  request({ method: 'post', url: '/api/admin/providers/health/recheck', signal });

// --- ключи провайдеров (замена без рестарта; ключи наружу НЕ отдаются) ---
export const getProviderKeys = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/admin/providers/keys', signal });

export const setProviderKey = (provider, apiKey, { signal } = {}) =>
  request({
    method: 'put',
    url: `/api/admin/providers/${encodeURIComponent(provider)}/api-key`,
    data: { api_key: apiKey },
    signal,
  });

export const deleteProviderKey = (provider, { signal } = {}) =>
  request({
    method: 'delete',
    url: `/api/admin/providers/${encodeURIComponent(provider)}/api-key`,
    signal,
  });

// --- эмбеддер MemOS (смена сбрасывает ВСЮ память MemOS) ---
export const setMemosEmbedder = (model, dimension, { signal } = {}) =>
  request({ method: 'put', url: '/api/admin/memos/embedder', data: { model, dimension }, signal });

export const wipeMemos = ({ signal } = {}) =>
  request({ method: 'post', url: '/api/admin/memos/wipe', signal });
