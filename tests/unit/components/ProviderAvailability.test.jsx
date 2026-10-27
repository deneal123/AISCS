import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ProviderAvailability from '@features/chat/components/ProviderAvailability';
import { useProviderStatus } from '@features/chat/hooks/useProviderStatus';

jest.mock('@features/chat/hooks/useProviderStatus');
jest.mock('@hooks/useResponsive', () => ({ useResponsive: () => ({ isMobile: true }) }));

const snapshot = (state = 'available') => ({
  state, ready: state === 'available' ? 2 : state === 'degraded' ? 1 : 0, total: 2,
  providers: [
    { id: 'gigachat', label: 'GigaChat', primary: true, state: 'ready' },
    { id: 'routerai', label: 'RouterAI', state: 'unavailable' },
    { id: 'openai', label: 'OpenAI', state: 'disabled' },
  ],
});

test('компактный индикатор сохраняет доступное название без видимой подписи', () => {
  useProviderStatus.mockReturnValue({ data: snapshot(), stale: false });
  render(<ChakraProvider><ProviderAvailability compact /></ChakraProvider>);
  const trigger = screen.getByRole('button', { name: 'ИИ доступен' });
  expect(trigger).toHaveTextContent('');
  expect(trigger).toHaveStyle({ width: '44px', height: '44px' });
});

test.each([
  ['available', 'ИИ доступен'], ['degraded', 'ИИ доступен частично'],
  ['unavailable', 'ИИ временно недоступен'], ['unknown', 'Доступность ИИ неизвестна'],
])('has a text alternative for %s', (state, label) => {
  useProviderStatus.mockReturnValue({ data: snapshot(state), stale: false });
  render(<ChakraProvider><ProviderAvailability /></ChakraProvider>);
  expect(screen.getByRole('button', { name: label })).toBeVisible();
});

test('tap shows providers without launching a check; Escape closes the panel', async () => {
  useProviderStatus.mockReturnValue({ data: snapshot(), stale: false });
  render(<ChakraProvider><ProviderAvailability /></ChakraProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'ИИ доступен' }));
  await waitFor(() => expect(screen.getByText('GigaChat')).toBeVisible());
  expect(screen.getByText('Основной')).toBeVisible();
  expect(screen.getByText('Выключен')).toBeVisible();
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.queryByText('GigaChat')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'ИИ доступен' }));
  await waitFor(() => expect(screen.getByText('GigaChat')).toBeVisible());
  expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  expect(screen.getByRole('dialog')).toHaveStyle({ transform: 'none' });
  expect(screen.getByRole('button', { name: 'Закрыть: Доступность ИИ' })).toBeVisible();
});

test.each(['ready', 'unavailable', 'disabled', 'unknown', 'stale'])(
  'local provider is displayed by the same status projection: %s', async state => {
    useProviderStatus.mockReturnValue({ data: { ...snapshot(), providers: [
      { id: 'local', label: 'Локальная модель', state },
    ] }, stale: false });
    render(<ChakraProvider><ProviderAvailability /></ChakraProvider>);
    fireEvent.click(screen.getByTestId('provider-availability'));
    expect(await screen.findByText('Локальная модель')).toBeVisible();
    expect(screen.getByRole('list')).toBeVisible();
  },
);

test('refresh failure labels retained counts as historical until a successful read', async () => {
  useProviderStatus.mockReturnValue({ data: snapshot(), stale: true });
  const { rerender } = render(<ChakraProvider><ProviderAvailability /></ChakraProvider>);
  expect(screen.getByRole('button', { name: 'Доступность ИИ: нет свежих данных' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Доступность ИИ: нет свежих данных' }));
  await waitFor(() => expect(screen.getByText('При последней проверке: 2 из 2')).toBeVisible());
  expect(screen.queryByText('Доступно провайдеров: 2 из 2')).not.toBeInTheDocument();
  expect(screen.getAllByText('Данные устарели')).toHaveLength(3);

  useProviderStatus.mockReturnValue({ data: snapshot('degraded'), stale: false });
  rerender(<ChakraProvider><ProviderAvailability /></ChakraProvider>);
  expect(screen.getByTestId('provider-availability')).toHaveAttribute('aria-label', 'ИИ доступен частично');
  expect(screen.getByText('Доступно провайдеров: 1 из 2')).toBeVisible();
  expect(screen.queryByText('При последней проверке: 2 из 2')).not.toBeInTheDocument();
  expect(screen.getByText('Выключен')).toBeVisible();
});
