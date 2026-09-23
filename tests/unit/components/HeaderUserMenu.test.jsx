import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { MemoryRouter } from 'react-router-dom';
import HeaderUserMenu from '@shared/ui/layout/HeaderUserMenu';

describe('HeaderUserMenu responsive sizing', () => {
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
