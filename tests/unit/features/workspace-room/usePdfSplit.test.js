import { act, renderHook } from '@testing-library/react';
import { usePdfSplit, useWorkbenchSplit } from '@features/workspace-room/model/usePdfSplit';

beforeEach(() => localStorage.removeItem('gpthub.pdf.split.x'));
const pointer = { currentTarget: {
  parentElement: { getBoundingClientRect: () => ({ left: 0, width: 1000 }) },
  setPointerCapture: jest.fn(),
}, pointerId: 1 };

it('commits the last pointer position even before its animation frame renders', () => {
  const { result } = renderHook(() => usePdfSplit('x', 50));
  act(() => {
    result.current.props.onPointerDown(pointer);
    result.current.props.onPointerMove({ clientX: 650 });
    result.current.props.onPointerUp();
  });
  expect(result.current.value).toBe(65);
  expect(localStorage.getItem('gpthub.pdf.split.x')).toBe('65');
});

it('cancels a drag without persisting a half-applied position', () => {
  const { result } = renderHook(() => usePdfSplit('x', 50));
  act(() => {
    result.current.props.onPointerDown(pointer);
    result.current.props.onPointerMove({ clientX: 650 });
    result.current.props.onPointerCancel();
  });
  expect(result.current.value).toBe(50);
  expect(localStorage.getItem('gpthub.pdf.split.x')).toBeNull();
});

it('starts IDE at the PDF half-width while retaining independent keyboard geometry', () => {
  localStorage.removeItem('gpthub.ide.split.x');
  localStorage.setItem('gpthub.pdf.split.x', '64');
  const { result } = renderHook(() => useWorkbenchSplit('x', 50, { namespace: 'ide', label: 'Ширина кода и агента' }));
  expect(result.current.value).toBe(50);
  expect(result.current.props['aria-label']).toBe('Ширина кода и агента');
  act(() => result.current.props.onKeyDown({ key: 'ArrowLeft', preventDefault: jest.fn() }));
  expect(result.current.value).toBe(48);
  expect(localStorage.getItem('gpthub.ide.split.x')).toBe('48');
  expect(localStorage.getItem('gpthub.pdf.split.x')).toBe('64');
});
