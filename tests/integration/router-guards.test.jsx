import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom';
import { APP_ROUTES, AuthOnlyRoute, GuestOnlyRoute, PublicRoute } from '@app/router';

const mockUseAuth = jest.fn();

jest.mock('@app/providers', () => ({
  useAuth: () => mockUseAuth(),
}));

// Новый роутинг: / — лендинг (guest-only), /chat — чат (auth-only).
function renderRoutes(initialPath) {
  return render(
    <ChakraProvider>
      <MemoryRouter
        initialEntries={[initialPath]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path={APP_ROUTES.ROOT} element={<GuestOnlyRoute><div>LANDING</div></GuestOnlyRoute>} />
          <Route path={APP_ROUTES.CHAT} element={<AuthOnlyRoute><div>CHAT</div></AuthOnlyRoute>} />
          <Route path={APP_ROUTES.LOGIN} element={<GuestOnlyRoute><div>LOGIN</div></GuestOnlyRoute>} />
          <Route path={APP_ROUTES.SIGNUP} element={<GuestOnlyRoute><div>SIGNUP</div></GuestOnlyRoute>} />
          <Route path={APP_ROUTES.REGISTER} element={<Navigate to={APP_ROUTES.SIGNUP} replace />} />
          <Route path="*" element={<PublicRoute><div>NOT_FOUND</div></PublicRoute>} />
        </Routes>
      </MemoryRouter>
    </ChakraProvider>
  );
}

describe('Router guards integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('redirects guest from /chat to /login', async () => {
    mockUseAuth.mockReturnValue({
      isSessionLoading: false,
      resolveGuardRedirect: (guard, location) => (guard === 'auth-only' ? { to: APP_ROUTES.LOGIN, state: { from: location } } : null),
    });

    renderRoutes(APP_ROUTES.CHAT);

    expect(await screen.findByText('LOGIN')).toBeInTheDocument();
  });

  it('redirects authenticated user from /login to /chat', async () => {
    mockUseAuth.mockReturnValue({
      isSessionLoading: false,
      resolveGuardRedirect: (guard) => (guard === 'guest-only' ? { to: APP_ROUTES.CHAT } : null),
    });

    renderRoutes(APP_ROUTES.LOGIN);

    expect(await screen.findByText('CHAT')).toBeInTheDocument();
  });

  it('renders landing at / for guest', async () => {
    mockUseAuth.mockReturnValue({
      isSessionLoading: false,
      resolveGuardRedirect: () => null,
    });

    renderRoutes(APP_ROUTES.ROOT);

    expect(await screen.findByText('LANDING')).toBeInTheDocument();
  });

  it('renders /signup for guest and serves fallback for unknown route', async () => {
    mockUseAuth.mockReturnValue({
      isSessionLoading: false,
      resolveGuardRedirect: () => null,
    });

    const { unmount } = renderRoutes(APP_ROUTES.SIGNUP);
    expect(await screen.findByText('SIGNUP')).toBeInTheDocument();

    unmount();
    renderRoutes('/missing-route');
    expect(await screen.findByText('NOT_FOUND')).toBeInTheDocument();
  });
});
