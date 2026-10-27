import { act, render, screen } from '@testing-library/react';
import CodePreview from '@shared/controls/CodePreview';

jest.mock('@shared/controls/CodeSyntax', () => ({ __esModule: true, default: () => { throw new Error('PRIVATE_CHUNK_ERROR'); } }));

it('retains literal source if the optional syntax layer fails', async () => {
  const expectedError = jest.spyOn(console, 'error').mockImplementation(() => {});
  try {
    let view;
    await act(async () => { view = render(<CodePreview value="<script>still readable</script>" />); });
    expect(screen.getByText('<script>still readable</script>')).toBeVisible();
    expect(view.container.querySelector('script')).toBeNull();
    expect(view.container).not.toHaveTextContent('PRIVATE_CHUNK_ERROR');
  } finally { expectedError.mockRestore(); }
});
