import { request } from './request';

export const login = (payload, options = {}) => request({ method: 'post', url: '/api/auth/v1/login', data: payload, ...options });

export const registerUser = (payload, options = {}) => request({ method: 'post', url: '/api/auth/v1/register', data: payload, ...options });

// Подтверждение email кодом: verify выдаёт сессию (cookie), resend шлёт новый код.
export const verifyEmailCode = (payload, options = {}) => request({ method: 'post', url: '/api/auth/v1/verify', data: payload, ...options });

export const resendEmailCode = (payload, options = {}) => request({ method: 'post', url: '/api/auth/v1/resend', data: payload, ...options });

export const logoutLocal = () => {
  document.cookie = 'auth_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
};
