jest.mock('../../../src/app/router', () => ({
  APP_ROUTES: { ROOT: '/', CHAT: '/chat', LOGIN: '/login', SIGNUP: '/signup', REGISTER: '/register' },
  ROUTE_CONFIG: [{ path: '/', preload: 'idle' }],
  ROUTE_LOADERS: { landing: jest.fn().mockResolvedValue({}), chat: jest.fn().mockResolvedValue({}),
    login: jest.fn().mockResolvedValue({}), signup: jest.fn().mockResolvedValue({}) },
}));

let scheduled;
let originalIdle;
let originalCancel;

beforeEach(() => {
  jest.resetModules();
  originalIdle = window.requestIdleCallback;
  originalCancel = window.cancelIdleCallback;
  window.requestIdleCallback = jest.fn((callback) => { scheduled = callback; return 7; });
  window.cancelIdleCallback = jest.fn();
  scheduled = null;
});

afterEach(() => {
  window.requestIdleCallback = originalIdle;
  window.cancelIdleCallback = originalCancel;
  window.history.replaceState({}, '', '/');
});

it('does not load the unrelated landing bundle while a chat is painting', () => {
  window.history.replaceState({}, '', '/chat/synthetic-thread');
  require('../../../src/hooks/useRoutePreload').preloadCriticalRoutes();
  scheduled?.();
  expect(require('../../../src/app/router').ROUTE_LOADERS.landing).not.toHaveBeenCalled();
});

it('does not start scheduled work after navigation away or cleanup', () => {
  window.history.replaceState({}, '', '/');
  const { preloadCriticalRoutes } = require('../../../src/hooks/useRoutePreload');
  const cancel = preloadCriticalRoutes();
  const callback = scheduled;
  window.history.replaceState({}, '', '/chat/synthetic-thread');
  callback();
  expect(require('../../../src/app/router').ROUTE_LOADERS.landing).not.toHaveBeenCalled();
  window.history.replaceState({}, '', '/');
  cancel();
  callback();
  expect(window.cancelIdleCallback).toHaveBeenCalledWith(7);
  expect(require('../../../src/app/router').ROUTE_LOADERS.landing).not.toHaveBeenCalled();
});

it('preserves explicit login intent and deduplicates successful loads', async () => {
  const { preloadRoute } = require('../../../src/hooks/useRoutePreload');
  preloadRoute('/login');
  await Promise.resolve();
  preloadRoute('/login');
  expect(require('../../../src/app/router').ROUTE_LOADERS.login).toHaveBeenCalledTimes(1);
});
