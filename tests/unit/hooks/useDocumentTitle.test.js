import { act, renderHook } from '@testing-library/react';
import useDocumentTitle from '../../../src/shared/hooks/useDocumentTitle';

describe('useDocumentTitle', () => {
  it('updates the route title without exposing page content', () => {
    const rendered = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: 'Чат' },
    });
    expect(document.title).toBe('Чат — GPTHub');

    act(() => rendered.rerender({ title: 'Работа' }));
    expect(document.title).toBe('Работа — GPTHub');
  });
});
