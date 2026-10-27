import React from 'react';
import { ChakraProvider } from '@chakra-ui/react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import AppTextarea from '../../../src/shared/controls/AppTextarea';

it('fits parent width changes outside observer delivery, ignoring its own height and scrollbar', () => {
  const originalObserver = global.ResizeObserver;
  let notify;
  const frames = [];
  global.ResizeObserver = jest.fn(callback => {
    notify = callback;
    return { observe: jest.fn(), disconnect: jest.fn() };
  });
  const frameSpy = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => {
    frames.push(callback); return frames.length;
  });
  const cancelSpy = jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  let view;
  try {
    view = render(<ChakraProvider><AppTextarea autoGrow aria-label="Document text" /></ChakraProvider>);
    const input = screen.getByRole('textbox', { name: 'Document text' });
    let width = 400;
    let height = 80;
    Object.defineProperty(input, 'offsetWidth', { get: () => width });
    Object.defineProperty(input, 'scrollHeight', { get: () => height });
    fireEvent.input(input);
    act(() => notify([{ contentRect: { width }, target: input }]));
    act(() => frames.shift()());
    expect(input.style.height).toBe('80px');

    width = 300; height = 160;
    act(() => notify([{ contentRect: { width }, target: input }]));
    expect(input.style.height).toBe('80px');
    act(() => frames.shift()());
    expect(input.style.height).toBe('160px');

    height = 200;
    act(() => notify([{ contentRect: { width: 290 }, target: input }]));
    act(() => frames.shift()());
    expect(input.style.height).toBe('160px');
    width = 250;
    act(() => notify([{ contentRect: { width }, target: input }]));
    view.unmount();
    expect(cancelSpy).toHaveBeenCalled();
    act(() => frames.shift()());
    expect(input.style.height).toBe('160px');
  } finally {
    view?.unmount();
    global.ResizeObserver = originalObserver;
    frameSpy.mockRestore(); cancelSpy.mockRestore();
  }
});
