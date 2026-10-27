import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfMaterialsPanel } from '@features/workspace-room/components/PdfMaterialsPanel';
import { groupPdfMaterials } from '@features/workspace-room/model/pdfMaterials';

const entries = ['main.tex', '.gitignore', 'document.toml', 'gpthub-core.sty', 'artifacts/build/document.pdf']
  .map(name => ({ path: `documents/a/${name}`, type: 'file', size: 12 }));
const work = { document: { project: { path: 'documents/a' } }, file: { path: 'documents/a/main.tex' },
  hub: { workspace: { state: 'ready', entries } }, load: jest.fn() };
const ui = (value = work) => <ChakraProvider><PdfMaterialsPanel work={value} onOpenFile={() => {}} /></ChakraProvider>;

it('separates ancillary files without losing or duplicating entries from any material group', () => {
  const source = [...entries, { path: 'documents/b/main.tex', type: 'file' }, { path: 'notes.md', type: 'file' }];
  const groups = groupPdfMaterials(source, 'documents/a');
  expect(groups.sources.map(item => item.path)).toEqual(['documents/a/main.tex']);
  expect(groups.service).toHaveLength(3);
  expect(groups.builds).toHaveLength(1);
  expect(groups.shared.map(item => item.path)).toEqual(['notes.md']);
  expect(Object.values(groups).flat()).toHaveLength(6);
});

it('keeps the primary source visible and technical files discoverable behind one keyboard disclosure', async () => {
  render(ui());
  expect(screen.getByRole('button', { name: 'documents/a/main.tex' })).toBeVisible();
  const technical = screen.getByRole('button', { name: /Служебные файлы/ });
  expect(technical).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(technical);
  await waitFor(() => expect(screen.getByRole('button', { name: 'documents/a/document.toml' })).toBeVisible());
  expect(screen.getByRole('button', { name: /Общие файлы чата/ })).toBeDisabled();
  expect(screen.queryByText('Каталог пока пуст.')).not.toBeVisible();
});

it('opens a selected ancillary source but preserves a deliberate collapse on background refresh', async () => {
  const value = { ...work, file: { path: 'documents/a/document.toml' } };
  const view = render(ui(value));
  const technical = screen.getByRole('button', { name: /Служебные файлы/ });
  await waitFor(() => expect(technical).toHaveAttribute('aria-expanded', 'true'));
  fireEvent.click(technical);
  view.rerender(ui({ ...value, hub: { workspace: { state: 'ready', entries: [...entries] } } }));
  expect(technical).toHaveAttribute('aria-expanded', 'false');
});
