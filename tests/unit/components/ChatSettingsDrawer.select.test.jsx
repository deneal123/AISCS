import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import ChatSettingsDrawer from '@features/chat/components/drawers/ChatSettingsDrawer';

it('keeps whisper options inside the settings focus owner and commits the selected model', async () => {
  const setChatUiSettings = jest.fn();
  render(<ChakraProvider theme={theme}><ChatSettingsDrawer isOpen onClose={jest.fn()}
    transcriptionConfig={{ local_enabled: true, default_model: 'base', models: ['base', 'small'] }}
    transcriptionMode="local" transcriptionModel="" setChatUiSettings={setChatUiSettings} />
  </ChakraProvider>);
  const input = await screen.findByRole('combobox', { name: 'Модель whisper', exact: true });
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  const option = await screen.findByRole('option', { name: 'small', exact: true });
  expect(option.closest('[role="dialog"]')).toBe(screen.getByRole('dialog'));
  fireEvent.click(option);
  expect(setChatUiSettings).toHaveBeenCalledTimes(1);
  const update = setChatUiSettings.mock.calls[0][0];
  expect(update({ transcriptionMode: 'local', transcriptionModel: '' })).toEqual({ transcriptionMode: 'local', transcriptionModel: 'small' });
});

it('offers only tool-capable research models and saves an independent research choice', async () => {
  const setChatUiSettings = jest.fn();
  render(<ChakraProvider theme={theme}><ChatSettingsDrawer isOpen onClose={jest.fn()}
    modelCatalog={{ giga: { id: 'GigaChat-2', capabilities: ['tools'] },
      text: { id: 'text-only', capabilities: [] } }} setChatUiSettings={setChatUiSettings} />
  </ChakraProvider>);
  const input = await screen.findByRole('combobox', { name: 'Модель ресёрча', exact: true });
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  expect(screen.queryByRole('option', { name: 'text-only' })).not.toBeInTheDocument();
  const option = await screen.findByRole('option', { name: 'GigaChat-2', exact: true });
  expect(option.closest('[role="dialog"]')).toBe(screen.getByRole('dialog'));
  fireEvent.click(option);
  const update = setChatUiSettings.mock.calls[0][0];
  expect(update({ preferredModel: 'chat-choice', ldrModel: '' })).toEqual({ preferredModel: 'chat-choice', ldrModel: 'GigaChat-2' });
});

it('exposes rich-catalog recovery without silently clearing a saved research model', async () => {
  const retry = jest.fn();
  const setChatUiSettings = jest.fn();
  render(<ChakraProvider theme={theme}><ChatSettingsDrawer isOpen onClose={jest.fn()}
    ldrModel="saved-model" modelCatalogStatus="error" onRetryModels={retry}
    setChatUiSettings={setChatUiSettings} /></ChakraProvider>);
  expect(await screen.findByText(/Не удалось загрузить сведения о моделях/)).toBeVisible();
  expect(screen.getByText('saved-model')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку моделей' }));
  expect(retry).toHaveBeenCalledTimes(1);
  expect(setChatUiSettings).not.toHaveBeenCalled();
});

it.each([
  ['loading', 'Загружаю модели ресёрча…'],
  ['ready', 'В каталоге нет моделей с подтверждённой поддержкой инструментов.'],
])('explains the %s research catalog state without inventing supported models', async (status, text) => {
  render(<ChakraProvider theme={theme}><ChatSettingsDrawer isOpen onClose={jest.fn()}
    modelCatalogStatus={status} modelCatalog={{ unknown: { id: 'unknown' } }}
    setChatUiSettings={jest.fn()} /></ChakraProvider>);
  expect(await screen.findByText(text)).toBeVisible();
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Модель ресёрча' }), { key: 'ArrowDown' });
  expect(screen.getAllByRole('option')).toHaveLength(1);
  expect(screen.getByRole('option', { name: 'По умолчанию' })).toBeInTheDocument();
});
