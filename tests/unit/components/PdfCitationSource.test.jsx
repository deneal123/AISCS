import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfCitationSource } from '@features/workspace-room/components/PdfCitationSource';

const inventory = { status: 'ready', sources: [], unresolved: 0, retry: jest.fn() };
const ui = (props) => <ChakraProvider><PdfCitationSource inventory={inventory} {...props} /></ChakraProvider>;

it('keeps a missing citation visible and never silently changes it', () => {
  const change = jest.fn();
  render(ui({ value: 7, onChange: change }));
  expect(screen.getByText('Источник 7 · нет в списке')).toBeInTheDocument();
  expect(screen.getByText(/пока нет доступных зарегистрированных источников/)).toBeInTheDocument();
  expect(change).not.toHaveBeenCalled();
});

it('provides a read retry without dropping an existing citation', () => {
  render(ui({ value: 7, inventory: { ...inventory, status: 'unavailable' } }));
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку источников' }));
  expect(inventory.retry).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Ссылки в черновике сохранены/)).toBeInTheDocument();
});

it('renders metadata as inert text, not a link or interpreted markup', () => {
  render(ui({ value: 1, inventory: { ...inventory, sources: [{ source_id: 1, value: '1',
    label: '<img src=x onerror=alert(1)>', author: 'Автор', url: 'javascript:alert(1)' }] } }));
  expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(document.querySelector('img')).toBeNull();
});
