import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import RouteErrorBoundary from '../../../src/app/router/RouteErrorBoundary';
import ErrorBoundary from '../../../src/shared/ui/molecules/ErrorBoundary';

const PRIVATE = 'PRIVATE_RENDER_EXCEPTION_BODY';
function BrokenPage() { throw new Error(PRIVATE); }

beforeEach(() => { jest.spyOn(console, 'error').mockImplementation(() => {}); });
afterEach(() => { jest.restoreAllMocks(); });

it('keeps the layout and uses a safe eagerly available child route fallback', async () => {
  const router = createMemoryRouter([{
    path: '/', element: <><header>Сохранённая навигация</header><main><Outlet /></main></>,
    errorElement: <RouteErrorBoundary />,
    children: [{ path: 'broken', element: <BrokenPage />, errorElement: <RouteErrorBoundary /> }],
  }], { initialEntries: ['/broken'] });
  render(<ChakraProvider><RouterProvider router={router} /></ChakraProvider>);
  expect(await screen.findByRole('heading', { name: 'Не удалось открыть страницу' })).toBeInTheDocument();
  expect(screen.getByText('Сохранённая навигация')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'На главную' })).toHaveAttribute('href', '/');
  expect(screen.getByRole('button', { name: 'Обновить страницу' })).toBeInTheDocument();
  expect(screen.queryByText('Попробовать снова')).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain(PRIVATE);
  expect(document.body.textContent).not.toContain('Unexpected Application Error');
  expect(document.title).toBe('Ошибка страницы — GPTHub');
});

it('bounds shared component diagnostics even when legacy showDetails is requested', async () => {
  const diagnostics = jest.fn();
  render(<ChakraProvider><ErrorBoundary showDetails onError={diagnostics}><BrokenPage /></ErrorBoundary></ChakraProvider>);
  expect(await screen.findByRole('heading', { name: 'Не удалось открыть страницу' })).toBeInTheDocument();
  expect(document.body.textContent).not.toContain(PRIVATE);
  expect(diagnostics).toHaveBeenCalledWith({ component: 'render_boundary', code: 'internal' });
  expect(diagnostics).toHaveBeenCalledTimes(1);
});

it('does not hand exception bodies to a custom app fallback', () => {
  const fallback = jest.fn(() => <p>Безопасная заглушка</p>);
  render(<ChakraProvider><ErrorBoundary fallbackRender={fallback}><BrokenPage /></ErrorBoundary></ChakraProvider>);
  expect(fallback).toHaveBeenCalledWith(expect.objectContaining({ error: { code: 'internal' }, errorInfo: null }));
  expect(JSON.stringify(fallback.mock.calls)).not.toContain(PRIVATE);
});
