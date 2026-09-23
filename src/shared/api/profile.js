import { request } from './request';
import { mapProfileDto } from './dtoMappers';

export const fetchProfile = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/profile/me', signal }, mapProfileDto);

export const updateProfile = (payload, { signal } = {}) =>
  request({ method: 'patch', url: '/api/profile/me', data: payload, signal }, mapProfileDto);

/**
 * Тумблеры писем. Шлём ТОЛЬКО изменённое поле: непереданное бэкенд трактует как
 * «не трогать», иначе переключение одного тумблера гасило бы второе согласие.
 */
export const updateNotificationPrefs = (payload, { signal } = {}) =>
  request({ method: 'patch', url: '/api/profile/me/notifications', data: payload, signal }, mapProfileDto);

export const deleteChatHistory = ({ signal } = {}) =>
  request({ method: 'delete', url: '/api/profile/me/chat-history', signal });

/** Баланс кредитов пользователя (проксирует billing API). */
export const getUserQuota = ({ signal } = {}) =>
  request({ method: 'get', url: '/api/billing/balance', signal });
