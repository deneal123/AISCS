import { APP_ROUTES } from '@app/router';
import { FiCreditCard, FiFileText, FiFolder, FiMessageSquare, FiShield } from '@shared/icons';

/** Header shortcuts use the same URL-backed surfaces and router dirty guard. */
export function getHeaderNavigation(location, isAdmin = false) {
  const onChat = /^\/chat(?:\/|$)/.test(location.pathname);
  const requested = new URLSearchParams(location.search).get('surface');
  const activeSurface = ['work', 'pdf'].includes(requested) ? requested : 'chat';
  const surfaces = [
    ['chat', 'Чат', FiMessageSquare],
    ['work', 'IDE', FiFolder],
    ['pdf', 'PDF', FiFileText],
  ].map(([surface, label, icon]) => {
    const params = new URLSearchParams(onChat ? location.search : '');
    params.delete('profile');
    if (surface === 'chat') params.delete('surface');
    else params.set('surface', surface);
    const search = params.toString();
    return {
      label, icon,
      to: `${onChat ? location.pathname : APP_ROUTES.CHAT}${search ? `?${search}` : ''}`,
      isActive: onChat && activeSurface === surface,
    };
  });
  return [
    ...surfaces,
    { label: 'Тарифы', to: APP_ROUTES.BILLING, icon: FiCreditCard },
    ...(isAdmin ? [{ label: 'Админ', to: APP_ROUTES.ADMIN, icon: FiShield }] : []),
  ];
}
