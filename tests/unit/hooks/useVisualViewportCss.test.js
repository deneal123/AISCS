import { act, renderHook } from '@testing-library/react';
import useVisualViewportCss from '@shared/hooks/useVisualViewportCss';

describe('shared visual viewport geometry', () => {
  const original = window.visualViewport;
  let viewport;
  let pending;
  beforeEach(() => {
    viewport = new EventTarget();
    Object.assign(viewport, { height: 800, offsetTop: 0 });
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { pending = callback; return 1; });
    jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  });
  afterEach(() => {
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: original });
    jest.restoreAllMocks();
  });
  it('tracks keyboard resize and pan before measuring, cleans listeners and CSS on unmount', () => {
    const { unmount } = renderHook(() => useVisualViewportCss());
    const style = document.documentElement.style;
    expect(style.getPropertyValue('--app-visual-height')).toBe('800px');
    act(() => {
      viewport.height = 350; viewport.offsetTop = 60;
      viewport.dispatchEvent(new Event('resize')); viewport.dispatchEvent(new Event('scroll'));
      pending();
    });
    expect(style.getPropertyValue('--app-visual-height')).toBe('350px');
    expect(style.getPropertyValue('--app-visual-top')).toBe('60px');
    unmount();
    expect(style.getPropertyValue('--app-visual-height')).toBe('');
    expect(style.getPropertyValue('--app-visual-top')).toBe('');
    window.requestAnimationFrame.mockClear();
    viewport.dispatchEvent(new Event('resize'));
    expect(window.requestAnimationFrame).not.toHaveBeenCalled();
  });
  it('uses the layout viewport when visualViewport is unavailable', () => {
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: undefined });
    const { unmount } = renderHook(() => useVisualViewportCss());
    expect(document.documentElement.style.getPropertyValue('--app-visual-height')).toBe(`${window.innerHeight}px`);
    unmount();
  });
});
