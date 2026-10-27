import React from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SettingsPanel from '../../../src/features/admin/components/SettingsPanel';
import { getAdminSettings, putAdminSetting, resetAdminSetting } from '@api/admin';

jest.mock('@api/admin', () => ({
  getAdminSettings: jest.fn(), putAdminSetting: jest.fn(), resetAdminSetting: jest.fn(),
}));
jest.mock('@shared/hooks/useAppToast', () => ({ useAppToast: () => jest.fn() }));

const specs = [
  { key: 'first', label: 'Первая', group: 'Группа', type: 'str', value: 'one', default: 'default', overridden: true },
  { key: 'second', label: 'Вторая', group: 'Группа', type: 'str', value: 'two', default: 'two', overridden: false },
];
const button = (input, name) => within(input.closest('.chakra-stack').parentElement)
  .getByRole('button', { name, exact: true });
const show = async () => {
  render(<ChakraProvider><SettingsPanel /></ChakraProvider>);
  return screen.findByRole('textbox', { name: 'Первая' });
};

beforeEach(() => {
  window.scrollTo = jest.fn();
  jest.clearAllMocks();
  getAdminSettings.mockResolvedValue({ settings: specs });
  putAdminSetting.mockResolvedValue({ status: 'ok', value: 'saved' });
  resetAdminSetting.mockResolvedValue({ status: 'ok', reset: true });
});

it('keeps sibling dirty input mounted during and after save refresh', async () => {
  const first = await show();
  const second = screen.getByRole('textbox', { name: 'Вторая' });
  fireEvent.change(second, { target: { value: 'unsaved sibling' } });
  let resolve;
  getAdminSettings.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  fireEvent.click(button(first, 'Сохранить'));
  await waitFor(() => expect(getAdminSettings).toHaveBeenCalledTimes(2));
  expect(second).toBeInTheDocument();
  expect(second).toHaveValue('unsaved sibling');
  await act(async () => resolve({ settings: specs }));
  expect(screen.getByRole('textbox', { name: 'Вторая' })).toBe(second);
  expect(second).toHaveValue('unsaved sibling');
});

it('keeps cached fields on refresh failure and retries without another mutation', async () => {
  const first = await show();
  const second = screen.getByRole('textbox', { name: 'Вторая' });
  fireEvent.change(second, { target: { value: 'retained' } });
  getAdminSettings.mockRejectedValueOnce(new Error('private-refresh-sentinel'));
  fireEvent.click(button(first, 'Сохранить'));
  expect(await screen.findByText('Не удалось обновить настройки. Показаны последние доступные значения.')).toBeInTheDocument();
  expect(second).toHaveValue('retained');
  expect(document.body).not.toHaveTextContent('private-refresh-sentinel');
  fireEvent.click(screen.getByRole('button', { name: /Повторить/ }));
  await waitFor(() => expect(getAdminSettings).toHaveBeenCalledTimes(3));
  expect(putAdminSetting).toHaveBeenCalledTimes(1);
  expect(second).toHaveValue('retained');
});

it('resets only the acknowledged field, retaining another draft', async () => {
  const first = await show();
  const second = screen.getByRole('textbox', { name: 'Вторая' });
  fireEvent.change(first, { target: { value: 'discard on explicit reset' } });
  fireEvent.change(second, { target: { value: 'retain sibling' } });
  getAdminSettings.mockResolvedValueOnce({ settings: [{ ...specs[0], value: 'default', overridden: false }, specs[1]] });
  fireEvent.click(button(first, 'Сбросить'));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Первая' })).toHaveValue('default'));
  expect(screen.getByRole('textbox', { name: 'Вторая' })).toBe(second);
  expect(second).toHaveValue('retain sibling');
  expect(resetAdminSetting).toHaveBeenCalledWith('first');
});

it('aborts an initial read on unmount and ignores its late response', async () => {
  let resolve;
  getAdminSettings.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const view = render(<ChakraProvider><SettingsPanel /></ChakraProvider>);
  await waitFor(() => expect(getAdminSettings).toHaveBeenCalledTimes(1));
  const signal = getAdminSettings.mock.calls[0][0].signal;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => resolve({ settings: specs }));
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
});

it('does not start a refresh after a mutation completes on an unmounted panel', async () => {
  let resolve;
  putAdminSetting.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const view = render(<ChakraProvider><SettingsPanel /></ChakraProvider>);
  const first = await screen.findByRole('textbox', { name: 'Первая' });
  fireEvent.click(button(first, 'Сохранить'));
  await waitFor(() => expect(putAdminSetting).toHaveBeenCalledTimes(1));
  view.unmount();
  await act(async () => resolve({ status: 'ok', value: 'saved' }));
  expect(getAdminSettings).toHaveBeenCalledTimes(1);
});
