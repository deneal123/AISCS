import React from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { fireEvent, render, screen } from '@testing-library/react';
import AdminPage from '../../../src/features/admin/page/AdminPage';

jest.mock('@app/providers', () => ({ useLayoutControls: () => ({ setVariant: jest.fn() }) }));
jest.mock('@shared/motion/Reveal', () => ({
  Reveal: ({ children }) => <div className="in-view-reveal">{children}</div>,
}));
jest.mock('../../../src/features/admin/components/AnalyticsPanel', () => () => <button>Analytics fixture</button>);
jest.mock('../../../src/features/admin/components/SettingsPanel', () => () => <button>Settings fixture</button>);
jest.mock('../../../src/features/admin/components/PricingPanel', () => () => <button>Pricing fixture</button>);
jest.mock('../../../src/features/admin/components/UsersPanel', () => () => <button>Users fixture</button>);

it('keeps interactive admin panels outside decorative opacity reveals', () => {
  render(<ChakraProvider><AdminPage /></ChakraProvider>);
  for (const [tab, control] of [
    ['Аналитика', 'Analytics fixture'], ['Настройки', 'Settings fixture'],
    ['Тарифы и цены', 'Pricing fixture'], ['Пользователи', 'Users fixture'],
  ]) {
    fireEvent.click(screen.getByRole('tab', { name: tab, exact: true }));
    expect(screen.getByRole('button', { name: control }).closest('.in-view-reveal')).toBeNull();
  }
});

it('makes all admin destinations discoverable without a hidden horizontal scroller', () => {
  render(<ChakraProvider><AdminPage /></ChakraProvider>);
  const list = screen.getByRole('tablist', { name: 'Разделы админки' });
  expect(list).toHaveStyle({ flexWrap: 'wrap', maxWidth: '100%' });
  expect(screen.queryByRole('region', { name: 'Разделы админ-панели' })).toBeNull();
  expect(screen.getAllByRole('tab')).toHaveLength(4);
});
