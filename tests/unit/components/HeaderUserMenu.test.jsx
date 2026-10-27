import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { MemoryRouter } from 'react-router-dom';
import HeaderUserMenu from '@shared/ui/layout/HeaderUserMenu';
import { getHeaderNavigation } from '@shared/ui/layout/headerNavigation';

describe('HeaderUserMenu responsive sizing', () => {
  it.each(['chat', 'work', 'pdf'])('links to all thread surfaces and marks only %s current', async (surface) => {
    const location = { pathname: '/chat/thread-1', search: `?surface=${surface}&profile=open&keep=1` };
    render(<ChakraProvider><MemoryRouter initialEntries={[`${location.pathname}${location.search}`]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <HeaderUserMenu userLabel="S" user={{ email: 'synthetic@example.test' }} navigate={jest.fn()} logout={jest.fn()}
        navItems={getHeaderNavigation(location)} />
    </MemoryRouter></ChakraProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Меню аккаунта' }));
    const expected = { Чат: '/chat/thread-1?keep=1', IDE: '/chat/thread-1?surface=work&keep=1', PDF: '/chat/thread-1?surface=pdf&keep=1' };
    for (const [label, href] of Object.entries(expected)) {
      const item = await screen.findByRole('menuitem', { name: label, exact: true });
      expect(item.tagName).toBe('A');
      expect(item).toHaveAttribute('href', href);
      expect(item).toHaveStyle({ height: '34px', minHeight: '34px' });
    }
    const active = screen.getAllByRole('menuitem').filter((item) => item.hasAttribute('aria-current'));
    expect(active).toHaveLength(1);
    expect(active[0]).toHaveTextContent({ chat: 'Чат', work: 'IDE', pdf: 'PDF' }[surface]);
    expect(screen.queryByRole('menuitem', { name: 'Админ', exact: true })).not.toBeInTheDocument();
  });

  it('preserves the PDF surface when opening Profile', async () => {
    const navigate = jest.fn();
    render(<ChakraProvider><MemoryRouter initialEntries={['/chat/thread-1?surface=pdf&keep=1']}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <HeaderUserMenu userLabel="S" user={{}} navigate={navigate} logout={jest.fn()} />
    </MemoryRouter></ChakraProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Меню аккаунта' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Профиль', exact: true }));
    expect(navigate).toHaveBeenCalledWith('/chat/thread-1?surface=pdf&keep=1&profile=open');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });

  it('enters the chosen surface from another page and retains role-gated Admin', () => {
    const nav = getHeaderNavigation({ pathname: '/billing', search: '?unrelated=1' }, true);
    expect(nav.slice(0, 3).map(({ to, isActive }) => [to, isActive])).toEqual([
      ['/chat', false], ['/chat?surface=work', false], ['/chat?surface=pdf', false],
    ]);
    expect(nav.map(({ label }) => label)).toEqual(['Чат', 'IDE', 'PDF', 'Тарифы', 'Админ']);
  });

  it('bounds the portal menu when the account email has a long local part', async () => {
    render(
      <ChakraProvider>
        <MemoryRouter
          initialEntries={['/chat/thread-1?surface=work']}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <HeaderUserMenu
            userLabel="S"
            user={{
              first_name: 'Synthetic acceptance account',
              email: `${'mobile-work-hub-acceptance-'.repeat(4)}@example.test`,
            }}
            navigate={jest.fn()}
            logout={jest.fn()}
          />
        </MemoryRouter>
      </ChakraProvider>,
    );

    fireEvent.click(screen.getByRole('button'));

    const menu = await screen.findByTestId('header-user-menu');
    expect(menu).toHaveStyle({
      width: '280px',
      minWidth: '0',
      maxWidth: 'calc(100vw - 32px)',
    });
    expect(screen.getAllByText(/mobile-work-hub-acceptance-/)).toHaveLength(2);
  });
});
