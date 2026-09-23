import { useEffect } from 'react';
import { APP_ROUTES } from '../app/router';
import { ROUTE_CONFIG, ROUTE_LOADERS } from '../app/router';

const loaded = new Set();

const intentPreloadByPath = {
  [APP_ROUTES.LOGIN]: ROUTE_LOADERS.login,
  [APP_ROUTES.SIGNUP]: ROUTE_LOADERS.signup,
  [APP_ROUTES.REGISTER]: ROUTE_LOADERS.signup,
};

const idlePreloadByPath = {
  [APP_ROUTES.ROOT]: ROUTE_LOADERS.landing,
  [APP_ROUTES.CHAT]: ROUTE_LOADERS.chat,
};

const idleRoutes = ROUTE_CONFIG.filter((item) => item.preload === 'idle').map((item) => item.path);

export const preloadRoute = (path) => {
  const loader = intentPreloadByPath[path];
  if (!loader || loaded.has(path)) return;
  loader().then(() => loaded.add(path)).catch(() => undefined);
};

export const preloadCriticalRoutes = () => {
  if (typeof window === 'undefined') return;
  const runner = () => {
    idleRoutes.forEach((path) => {
      const loader = idlePreloadByPath[path];
      if (!loader || loaded.has(path)) return;
      loader().then(() => loaded.add(path)).catch(() => undefined);
    });
  };
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(runner, { timeout: 3000 });
    return;
  }
  setTimeout(runner, 1200);
};

export const useRoutePreload = () => {
  useEffect(() => {
    preloadCriticalRoutes();
  }, []);

  return { preloadRoute };
};
