import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatPageAuxiliaryLayers from '../../../src/features/chat/components/ChatPageAuxiliaryLayers';
import MemoryDrawer from '../../../src/features/chat/components/drawers/ChatMemoryDrawer';

jest.mock('../../../src/features/chat/components/drawers/ChatMemoryDrawer', () => jest.fn(() => null));
jest.mock('../../../src/features/chat/components/drawers/ChatGraphDrawer', () => () => null);
jest.mock('../../../src/features/chat/components/drawers/ChatSettingsDrawer', () => () => null);
jest.mock('@features/profile', () => ({ ProfileDrawer: () => null }));
jest.mock('../../../src/features/chat/components/ChatCommandPalette', () => () => null);

const EmptyAuth = () => null;
const closed = { isOpen: false, onClose: () => {} };

it('does not re-render a mounted drawer for unrelated parent activity but accepts changed data and close', async () => {
  MemoryDrawer.mockClear();
  const memory = { disclosure: { isOpen: true, onClose: () => {} }, facts: [], dashboard: {} };
  const props = {
    sidebar: { disclosure: closed, render: () => null }, palette: { state: { isOpen: false } },
    auth: { Component: EmptyAuth }, surface: {}, memory,
    graph: { disclosure: closed }, settings: { disclosure: closed }, profile: { disclosure: closed },
  };
  const view = render(<ChakraProvider><ChatPageAuxiliaryLayers {...props} /></ChakraProvider>);
  await waitFor(() => expect(MemoryDrawer).toHaveBeenCalledTimes(1));
  view.rerender(<ChakraProvider><ChatPageAuxiliaryLayers {...props} memory={{ ...memory }} palette={{ ...props.palette }} /></ChakraProvider>);
  expect(MemoryDrawer).toHaveBeenCalledTimes(1);
  const changed = { ...memory, facts: [{ id: 'synthetic-fact' }] };
  view.rerender(<ChakraProvider><ChatPageAuxiliaryLayers {...props} memory={changed} /></ChakraProvider>);
  expect(MemoryDrawer).toHaveBeenCalledTimes(2);
  view.rerender(<ChakraProvider><ChatPageAuxiliaryLayers {...props} memory={{ ...changed, disclosure: closed }} /></ChakraProvider>);
  expect(MemoryDrawer).toHaveBeenCalledTimes(3);
  expect(MemoryDrawer.mock.calls.at(-1)[0].isOpen).toBe(false);
});
