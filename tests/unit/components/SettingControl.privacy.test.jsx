import React from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SettingControl from '../../../src/features/admin/components/SettingControl';

const MARKER = 'private-provider-body-sentinel';
const spec = { key: 'test_setting', label: 'Настройка', type: 'str', value: 'initial', overridden: true };
const show = (props = {}) => render(
  <ChakraProvider><SettingControl spec={spec} onSave={jest.fn()} onReset={jest.fn()} {...props} /></ChakraProvider>,
);

it.each([
  [400, MARKER], [500, MARKER], [422, { message: MARKER }],
  [503, [{ msg: MARKER }]], [401, MARKER], [403, MARKER],
])('does not render raw server detail for HTTP %s', async (status, detail) => {
  const onSave = jest.fn().mockRejectedValue({ response: { status, data: { detail } } });
  show({ onSave });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'local edit' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить', exact: true }));
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить', exact: true })).toBeEnabled());
  expect(document.body).not.toHaveTextContent(MARKER);
  expect(screen.getByRole('textbox')).toHaveValue('local edit');
  expect(screen.getByRole('textbox')).toHaveAccessibleDescription(screen.getByRole('alert').textContent);
});

it.each([MARKER, { message: MARKER }, [{ msg: MARKER }]])('handles reset failure without exposing provider payload %#', async (detail) => {
  const onReset = jest.fn().mockRejectedValue({ response: { status: 503, data: { detail } } });
  show({ onReset });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'retained edit' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сбросить', exact: true }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен. Попробуйте позже.');
  expect(document.body).not.toHaveTextContent(MARKER);
  expect(screen.getByRole('textbox')).toHaveValue('retained edit');
  expect(onReset).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Сбросить', exact: true })).toBeEnabled();
});

it('blocks duplicate and competing operations while allowing an explicit retry', async () => {
  let reject;
  const held = new Promise((_, fail) => { reject = fail; });
  const onSave = jest.fn().mockReturnValueOnce(held).mockResolvedValueOnce(undefined);
  const onReset = jest.fn();
  show({ onSave, onReset });
  const save = screen.getByRole('button', { name: 'Сохранить', exact: true });
  fireEvent.click(save);
  fireEvent.click(save);
  fireEvent.click(screen.getByRole('button', { name: 'Сбросить', exact: true }));
  expect(onSave).toHaveBeenCalledTimes(1);
  expect(onReset).not.toHaveBeenCalled();
  await act(async () => reject({ response: { status: 503, data: { detail: MARKER } } }));
  expect(screen.getByRole('alert')).not.toHaveTextContent(MARKER);
  await act(async () => fireEvent.click(save));
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('preserves invalid JSON without dispatching and associates its local error', () => {
  const onSave = jest.fn();
  show({ spec: { ...spec, type: 'json', value: { valid: true } }, onSave });
  const input = screen.getByRole('textbox', { name: 'Настройка' });
  fireEvent.change(input, { target: { value: '{broken' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить', exact: true }));
  expect(onSave).not.toHaveBeenCalled();
  expect(input).toHaveValue('{broken');
  expect(input).toHaveFocus();
  expect(input).toHaveAttribute('aria-invalid', 'true');
  expect(input).toHaveAccessibleDescription('Невалидный JSON');
});
