import { act, renderHook } from '@testing-library/react';
import useToastActionProtection from '@shared/hooks/useToastActionProtection';

const property = '--app-toast-action-inset';

describe('toast action shelf protection', () => {
  let shelf;
  let queuedFrame;
  const originalHeight = window.innerHeight;
  const originalViewport = window.visualViewport;

  beforeEach(() => {
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
    shelf = document.createElement('div');
    shelf.setAttribute('data-toast-protected-actions', '');
    shelf.getBoundingClientRect = jest.fn(() => ({ top: 600, bottom: 660, width: 500, height: 60 }));
    document.body.appendChild(shelf);
    jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      queuedFrame = callback;
      return 1;
    });
    jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  });

  afterEach(() => {
    shelf.remove();
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight });
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: originalViewport });
    queuedFrame = undefined;
    jest.restoreAllMocks();
  });

  it('reserves real shelf position rather than a hard-coded viewport offset', () => {
    const { unmount } = renderHook(() => useToastActionProtection());
    expect(document.documentElement.style.getPropertyValue(property)).toBe('332px');
    unmount();
    expect(document.documentElement.style.getPropertyValue(property)).toBe('');
    expect(window.cancelAnimationFrame).toHaveBeenCalledWith(1);
  });

  it('ignores a hidden panel with no rendered area', () => {
    shelf.getBoundingClientRect.mockReturnValue({ top: 0, bottom: 0, width: 0, height: 0 });
    const { unmount } = renderHook(() => useToastActionProtection());
    expect(document.documentElement.style.getPropertyValue(property)).toBe('0px');
    unmount();
  });

  it('coalesces scrolling and recomputes the visible shelf', () => {
    const { unmount } = renderHook(() => useToastActionProtection());
    shelf.getBoundingClientRect.mockReturnValue({ top: 700, bottom: 760, width: 500, height: 60 });
    act(() => {
      document.dispatchEvent(new Event('scroll'));
      window.dispatchEvent(new Event('resize'));
      queuedFrame();
    });
    expect(document.documentElement.style.getPropertyValue(property)).toBe('232px');
    unmount();
  });

  it('keeps feedback in the visual viewport when the keyboard hides the shelf', () => {
    const viewport = new EventTarget();
    viewport.offsetTop = 0;
    viewport.height = 500;
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    const { unmount } = renderHook(() => useToastActionProtection());
    expect(document.documentElement.style.getPropertyValue(property)).toBe('400px');
    viewport.height = 700;
    act(() => {
      viewport.dispatchEvent(new Event('resize'));
      queuedFrame();
    });
    expect(document.documentElement.style.getPropertyValue(property)).toBe('332px');
    unmount();
  });
});
