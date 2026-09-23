import React, { Suspense } from 'react';
import { Navigate, createBrowserRouter, RouterProvider } from 'react-router-dom';
import { Center, Spinner } from '@chakra-ui/react';
import { ErrorBoundary } from '@shared/ui/molecules';
import { useRoutePreload } from './hooks/useRoutePreload';
import { APP_ROUTES, FALLBACK_ROUTE, ROUTE_CONFIG, RoutePages } from './app/router';
import { AdminOnlyRoute, AuthOnlyRoute, FeatureFlagRoute, GuestOnlyRoute, PublicRoute, ROUTE_GUARDS, ROUTE_LAYOUTS, layoutMap } from './app/router';
import useDocumentTitle from '@shared/hooks/useDocumentTitle';

function RouteSuspenseBoundary({ children }) {
  return <Suspense fallback={<Center h="100vh"><Spinner size="lg" /></Center>}>{children}</Suspense>;
}

function RouteDocumentTitle({ title, children }) {
  useDocumentTitle(title);
  return children;
}

const guardMap = {
  [ROUTE_GUARDS.PUBLIC]: PublicRoute,
  [ROUTE_GUARDS.AUTH_ONLY]: AuthOnlyRoute,
  [ROUTE_GUARDS.GUEST_ONLY]: GuestOnlyRoute,
  [ROUTE_GUARDS.ADMIN_ONLY]: AdminOnlyRoute,
  [ROUTE_GUARDS.FEATURE_FLAG]: FeatureFlagRoute,
};

const emptyBuckets = Object.values(ROUTE_LAYOUTS).reduce((acc, layout) => {
  acc[layout] = [];
  return acc;
}, {});

const childRoutesByLayout = ROUTE_CONFIG.reduce((acc, route) => {
  const Guard = guardMap[route.guard] ?? React.Fragment;
  const routeElement = route.redirectTo
    ? <Guard><RouteDocumentTitle title={route.title}><Navigate to={route.redirectTo} replace /></RouteDocumentTitle></Guard>
    : (() => {
      const PageComponent = RoutePages[route.page];
      return <Guard><RouteDocumentTitle title={route.title}><RouteSuspenseBoundary><PageComponent /></RouteSuspenseBoundary></RouteDocumentTitle></Guard>;
    })();

  acc[route.layout].push({
    ...(route.path === APP_ROUTES.ROOT ? { index: true } : { path: route.path.replace(/^\//, '') }),
    element: routeElement,
  });
  return acc;
}, emptyBuckets);

const FallbackPage = RoutePages[FALLBACK_ROUTE.page];
const FallbackGuard = guardMap[FALLBACK_ROUTE.guard] ?? React.Fragment;
// 404 живёт ВНУТРИ PublicLayout (шапка/футер/амбиентный фон), а не голой чёрной
// страницей — единый бренд-шелл. Catch-all '*' в детях public-лейаута.
childRoutesByLayout[ROUTE_LAYOUTS.PUBLIC].push({
  path: '*',
  element: <FallbackGuard><RouteDocumentTitle title={FALLBACK_ROUTE.title}><RouteSuspenseBoundary><FallbackPage /></RouteSuspenseBoundary></RouteDocumentTitle></FallbackGuard>,
});

// По одному родительскому маршруту на лейаут (все на '/'): React Router
// подберёт тот, чьи дети совпадут с URL — пути детей не пересекаются.
const layoutRoutes = Object.values(ROUTE_LAYOUTS).map((layout) => ({
  path: '/',
  element: layoutMap[layout],
  children: childRoutesByLayout[layout],
}));

const router = createBrowserRouter(layoutRoutes);

function App() {
  useRoutePreload();
  return <ErrorBoundary level="page"><RouterProvider router={router} /></ErrorBoundary>;
}

export default App;
