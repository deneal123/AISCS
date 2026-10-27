import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatHeaderBar from '@features/chat/components/ChatHeaderBar';
import ChatComposerPanel from '@features/chat/components/composer/ChatComposerPanel';

let mockMobile = true;
jest.mock('@hooks/useResponsive', () => ({ useResponsive: () => ({ isMobile: mockMobile }) }));
jest.mock('@features/billing', () => ({ CreditsPill: () => null, useBillingContext: () => ({}) }));
jest.mock('@features/chat/components/ProviderAvailability', () => ({ compact }) => (
  <button data-testid="provider-placement" data-compact={Boolean(compact)}>ИИ</button>
));

it('переносит единственный индикатор между мобильным композером и десктопной шапкой', () => {
  const content = <ChakraProvider><ChatHeaderBar /><ChatComposerPanel
    fileInputRef={React.createRef()} isAuthenticated /></ChakraProvider>;
  mockMobile = true;
  const view = render(content);
  expect(screen.getAllByTestId('provider-placement')).toHaveLength(1);
  expect(screen.getByTestId('provider-placement').closest('[data-composer-settings]')).not.toBeNull();
  expect(screen.getByTestId('provider-placement')).toHaveAttribute('data-compact', 'true');
  expect(screen.queryByRole('group', { name: 'Разделы треда' })).not.toBeInTheDocument();
  mockMobile = false;
  view.rerender(<ChakraProvider><ChatHeaderBar /><ChatComposerPanel
    fileInputRef={React.createRef()} isAuthenticated /></ChakraProvider>);
  expect(screen.getAllByTestId('provider-placement')).toHaveLength(1);
  expect(screen.getByTestId('provider-placement').closest('header')).not.toBeNull();
  expect(screen.getByRole('group', { name: 'Разделы треда' })).toBeVisible();
});
