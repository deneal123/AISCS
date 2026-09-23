import axios from 'axios';
import { mapApiError } from './dtoMappers';

export const resolveApiBaseUrl = () => {
  // CRA/webpack пробрасывает переменные через process.env (REACT_APP_*).
  // import.meta.env здесь не используется (это не Vite) и ломал парсинг в jest.
  const envApiBase = process.env?.REACT_APP_API_BASE_URL;
  if (envApiBase) return envApiBase;
  // Без явной переменной API должен оставаться same-origin: production nginx
  // проксирует /api, а CRA dev-server применяет package.json proxy. Это также
  // позволяет статическому E2E-серверу не обходить proxy с cross-origin CORS.
  return '/';
};

const DEFAULT_TIMEOUT_MS = 30000;
const RETRY_CONFIG = { retries: 2, retryDelayMs: 400 };
const PUBLIC_ENDPOINTS = ['/api/health', '/api/chats/', '/api/chats/*/message'];

let unauthorizedHandler = null;
let refreshTokenHandler = null;
let refreshRequest = null;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const isPublicEndpoint = (requestUrl = '') => PUBLIC_ENDPOINTS.some((endpoint) => requestUrl.includes(endpoint));
// Повторять можно ТОЛЬКО идемпотентные запросы. Таймаут (status === undefined)
// не означает «не выполнилось»: сервер мог успешно создать платёж
// (POST /api/billing/checkout) или поставить задачу со списанием кредитов, просто
// ответ не дошёл. Раньше ретраились все методы — повтор мог создать второй платёж.
const IDEMPOTENT_METHODS = new Set(['get', 'head', 'options']);
const isRetryableStatus = (status) => !status || status >= 500 || status === 429;
const isRetryable = (config, status) =>
  IDEMPOTENT_METHODS.has(String(config?.method || 'get').toLowerCase()) &&
  isRetryableStatus(status);

export const registerUnauthorizedHandler = (handler) => {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
};

export const registerRefreshTokenHandler = (handler) => {
  refreshTokenHandler = handler;
  return () => {
    if (refreshTokenHandler === handler) refreshTokenHandler = null;
  };
};

const httpClient = axios.create({
  baseURL: resolveApiBaseUrl(),
  withCredentials: true,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
});

httpClient.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined' ? window.localStorage.getItem('auth_token') : null;
  const headers = { ...(config.headers || {}) };
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }
  return {
    ...config,
    headers,
    timeout: config.timeout ?? DEFAULT_TIMEOUT_MS,
  };
});

httpClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config || {};
    const status = error.response?.status;

    if (axios.isCancel(error)) {
      return Promise.reject(mapApiError(error, { kind: 'canceled' }));
    }

    if (status === 401 && !config.__isRetryAfterRefresh && !isPublicEndpoint(config.url || '') && typeof refreshTokenHandler === 'function') {
      config.__isRetryAfterRefresh = true;
      refreshRequest = refreshRequest || Promise.resolve(refreshTokenHandler());
      try {
        await refreshRequest;
        return httpClient.request(config);
      } catch (refreshError) {
        if (typeof unauthorizedHandler === 'function') unauthorizedHandler();
        return Promise.reject(mapApiError(refreshError));
      } finally {
        refreshRequest = null;
      }
    }

    const retryCount = config.__retryCount || 0;
    if (isRetryable(config, status) && retryCount < RETRY_CONFIG.retries && !config.__skipRetry) {
      config.__retryCount = retryCount + 1;
      await sleep(RETRY_CONFIG.retryDelayMs * config.__retryCount);
      return httpClient.request(config);
    }

    if (status === 401 && !isPublicEndpoint(config.url || '') && typeof unauthorizedHandler === 'function') {
      unauthorizedHandler();
    }

    return Promise.reject(mapApiError(error));
  },
);

export default httpClient;
