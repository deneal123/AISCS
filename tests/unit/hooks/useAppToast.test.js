import { act, renderHook } from '@testing-library/react';
import { useAppToast } from '@shared/hooks/useAppToast';

const mockToast = jest.fn();
mockToast.isActive = jest.fn();
mockToast.update = jest.fn();
mockToast.close = jest.fn();

jest.mock('@chakra-ui/react', () => ({
  Box: 'div',
  Icon: 'span',
  Text: 'span',
  useToast: () => mockToast,
}));

describe('useAppToast responsive portal geometry', () => {
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    mockToast.mockReset();
    mockToast.isActive.mockReset();
    mockToast.update.mockReset();
    mockToast.close.mockReset();
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: originalInnerWidth,
    });
  });

  it('uses the bottom portal and viewport-bounded container on mobile', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 393 });
    const { result } = renderHook(() => useAppToast());

    act(() => result.current({ title: 'Сохранено' }));

    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({
      position: 'bottom',
      containerStyle: {
        width: 'min(360px, calc(100vw - 32px))',
        minWidth: 0,
        maxWidth: 'calc(100vw - 32px)',
        margin: '0 16px calc(112px + env(safe-area-inset-bottom, 0px))',
      },
    }));
  });

  it('keeps the bottom-right placement on desktop', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    const { result } = renderHook(() => useAppToast());

    act(() => result.current({ title: 'Сохранено' }));

    expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({
      position: 'bottom-right',
      containerStyle: expect.objectContaining({
        margin: '0 16px 88px',
      }),
    }));
  });

  it('updates one operation toast instead of stacking a duplicate', () => {
    mockToast.isActive.mockReturnValue(true);
    const { result } = renderHook(() => useAppToast());

    act(() => result.current({
      operationId: 'workspace-save',
      title: 'Сохраняю',
      status: 'info',
    }));
    act(() => result.current({
      operationId: 'workspace-save',
      title: 'Сохранено',
      status: 'success',
    }));

    expect(mockToast).toHaveBeenCalledTimes(1);
    expect(mockToast.update).toHaveBeenCalledWith(
      'operation:workspace-save',
      expect.objectContaining({ id: 'operation:workspace-save' }),
    );
  });
});
