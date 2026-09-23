import { lazy } from 'react';

export const APP_ROUTES = {
  ROOT: '/',
  CHAT: '/chat',
  LOGIN: '/login',
  SIGNUP: '/signup',
  REGISTER: '/register',
  CHAT_THREAD: '/chat/:threadId',
  PLATFORM: '/platform',
  PRICING: '/pricing',
  BILLING: '/billing',
  BILLING_SUCCESS: '/billing/success',
  LEGAL: '/legal/:docId',
  CONTACTS: '/contacts',
  ADMIN: '/admin',
  NOT_FOUND: '*',
};

export const ROUTE_GUARDS = {
  PUBLIC: 'public',
  GUEST_ONLY: 'guest-only',
  AUTH_ONLY: 'auth-only',
  ADMIN_ONLY: 'admin-only',
  FEATURE_FLAG: 'feature-flag',
};

export const ROUTE_LAYOUTS = {
  PUBLIC: 'public',
  PROTECTED: 'protected',
  AUTH: 'auth',
};

const loadLandingPage = () => import(/* webpackChunkName: "route-landing" */ '@pages/landing');
const loadPlatformPage = () => import(/* webpackChunkName: "route-platform" */ '@pages/platform');
const loadPricingPage = () => import(/* webpackChunkName: "route-pricing" */ '@pages/pricing');
const loadChatPage = () => import(/* webpackChunkName: "route-chat" */ '@pages/chat');
const loadLoginPage = () => import(/* webpackChunkName: "route-login" */ '@pages/login');
const loadSignUpPage = () => import(/* webpackChunkName: "route-signup" */ '@pages/signup');
const loadNotFoundPage = () => import(/* webpackChunkName: "route-notfound" */ '@pages/notFound');
const loadBillingPage = () => import(/* webpackChunkName: "route-billing" */ '@pages/billing');
const loadBillingSuccessPage = () =>
  import(/* webpackChunkName: "route-billing-success" */ '@pages/billingSuccess');
const loadLegalPage = () => import(/* webpackChunkName: "route-legal" */ '@pages/legal');
const loadContactsPage = () => import(/* webpackChunkName: "route-contacts" */ '@pages/contacts');
const loadAdminPage = () => import(/* webpackChunkName: "route-admin" */ '@pages/admin');

export const ROUTE_LOADERS = {
  landing: loadLandingPage,
  platform: loadPlatformPage,
  pricing: loadPricingPage,
  chat: loadChatPage,
  login: loadLoginPage,
  signup: loadSignUpPage,
  notfound: loadNotFoundPage,
  billing: loadBillingPage,
  billingSuccess: loadBillingSuccessPage,
  legal: loadLegalPage,
  contacts: loadContactsPage,
  admin: loadAdminPage,
};

export const RoutePages = {
  LandingPage: lazy(loadLandingPage),
  PlatformPage: lazy(loadPlatformPage),
  PricingPage: lazy(loadPricingPage),
  ChatPage: lazy(loadChatPage),
  LoginPage: lazy(loadLoginPage),
  SignUpPage: lazy(loadSignUpPage),
  NotFoundPage: lazy(loadNotFoundPage),
  BillingPage: lazy(loadBillingPage),
  BillingSuccessPage: lazy(loadBillingSuccessPage),
  LegalPage: lazy(loadLegalPage),
  ContactsPage: lazy(loadContactsPage),
  AdminPage: lazy(loadAdminPage),
};

export const ROUTE_CONFIG = [
  { path: APP_ROUTES.ROOT, title: 'Главная', page: 'LandingPage', guard: ROUTE_GUARDS.PUBLIC, layout: ROUTE_LAYOUTS.PUBLIC, preload: 'idle' },
  { path: APP_ROUTES.PLATFORM, title: 'Платформа', page: 'PlatformPage', guard: ROUTE_GUARDS.PUBLIC, layout: ROUTE_LAYOUTS.PUBLIC, preload: false },
  { path: APP_ROUTES.PRICING, title: 'Тарифы', page: 'PricingPage', guard: ROUTE_GUARDS.PUBLIC, layout: ROUTE_LAYOUTS.PUBLIC, preload: false },
  { path: APP_ROUTES.CHAT, title: 'Чат', page: 'ChatPage', guard: ROUTE_GUARDS.AUTH_ONLY, layout: ROUTE_LAYOUTS.PROTECTED, preload: false },
  { path: APP_ROUTES.CHAT_THREAD, title: 'Чат', page: 'ChatPage', guard: ROUTE_GUARDS.AUTH_ONLY, layout: ROUTE_LAYOUTS.PROTECTED, preload: false },
  { path: APP_ROUTES.BILLING, title: 'Баланс', page: 'BillingPage', guard: ROUTE_GUARDS.AUTH_ONLY, layout: ROUTE_LAYOUTS.PROTECTED, preload: false },
  { path: APP_ROUTES.BILLING_SUCCESS, title: 'Оплата завершена', page: 'BillingSuccessPage', guard: ROUTE_GUARDS.AUTH_ONLY, layout: ROUTE_LAYOUTS.PROTECTED, preload: false },
  { path: APP_ROUTES.ADMIN, title: 'Администрирование', page: 'AdminPage', guard: ROUTE_GUARDS.ADMIN_ONLY, layout: ROUTE_LAYOUTS.PROTECTED, preload: false },
  { path: APP_ROUTES.LEGAL, title: 'Документы', page: 'LegalPage', guard: ROUTE_GUARDS.PUBLIC, layout: ROUTE_LAYOUTS.PUBLIC, preload: false },
  { path: APP_ROUTES.CONTACTS, title: 'Контакты', page: 'ContactsPage', guard: ROUTE_GUARDS.PUBLIC, layout: ROUTE_LAYOUTS.PUBLIC, preload: false },
  { path: APP_ROUTES.LOGIN, title: 'Вход', page: 'LoginPage', guard: ROUTE_GUARDS.GUEST_ONLY, layout: ROUTE_LAYOUTS.AUTH, preload: 'intent' },
  { path: APP_ROUTES.SIGNUP, title: 'Регистрация', page: 'SignUpPage', guard: ROUTE_GUARDS.GUEST_ONLY, layout: ROUTE_LAYOUTS.AUTH, preload: 'intent' },
  { path: APP_ROUTES.REGISTER, title: 'Регистрация', redirectTo: APP_ROUTES.SIGNUP, guard: ROUTE_GUARDS.PUBLIC, layout: ROUTE_LAYOUTS.AUTH, preload: false },
];

export const FALLBACK_ROUTE = {
  path: APP_ROUTES.NOT_FOUND,
  page: 'NotFoundPage',
  title: 'Страница не найдена',
  guard: ROUTE_GUARDS.PUBLIC,
};

const AUTH_ROUTES = new Set([APP_ROUTES.LOGIN, APP_ROUTES.SIGNUP, APP_ROUTES.REGISTER]);

export const isAuthRoute = (pathname = '') => AUTH_ROUTES.has(pathname);

export const isLandingRoute = (pathname = '') => pathname === APP_ROUTES.ROOT;

export const isPlatformRoute = (pathname = '') => pathname === APP_ROUTES.PLATFORM;

export const isChatRoute = (pathname = '') => pathname === APP_ROUTES.CHAT || pathname.startsWith('/chat/');

export const shouldUseFullWidthLayout = (pathname = '') =>
  isChatRoute(pathname) || isLandingRoute(pathname) || isAuthRoute(pathname) ||
  pathname === APP_ROUTES.PLATFORM;
