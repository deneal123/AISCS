import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import { PdfStudioToolbar } from '@features/workspace-room/components/PdfStudioToolbar';
import { PdfBuildActivity } from '@features/workspace-room/components/PdfBuildActivity';

const makeDocument = (busy = '', state = 'building') => ({
  project: { path: 'documents/slides', mode: 'draft', locale: 'ru-RU', profile: { label: 'Презентация PDF 16:9' } },
  build: { build_id: 'build-1', state }, busy, selectProject: jest.fn(), cancelBuild: jest.fn(), buildProject: jest.fn(),
});

it('shows a single aligned project label with compact controls', () => {
  const document = makeDocument();
  const onPanel = jest.fn();
  render(<ChakraProvider theme={theme}><PdfStudioToolbar document={document}
    projects={[{ value: 'documents/slides', label: 'Презентация PDF 16:9' }]} onPanel={onPanel} /></ChakraProvider>);
  expect(screen.getAllByText('Презентация PDF 16:9')).toHaveLength(1);
  expect(screen.queryByText(/Русский.*Черновик/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Материалы', exact: true })).toHaveStyle({ height: '30px' });
  const materials = screen.getByRole('button', { name: 'Материалы', exact: true });
  fireEvent.click(materials);
  expect(onPanel).toHaveBeenCalledWith('Материалы', materials);
});

it('keeps the full credit notice in explicit help instead of a permanent dock row', async () => {
  render(<ChakraProvider theme={theme}><PdfStudioToolbar document={makeDocument()}
    projects={[]} onPanel={jest.fn()} /></ChakraProvider>);
  expect(screen.queryByTestId('pdf-tools-consent-notice')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Работа PDF и расход кредитов' }));
  expect(await screen.findByTestId('pdf-tools-consent-notice')).toHaveTextContent('могут расходовать кредиты');
  const close = screen.getByRole('button', { name: 'Закрыть: Работа с PDF' });
  expect(close).toHaveFocus();
  fireEvent.click(close);
  expect(screen.queryByTestId('pdf-tools-consent-notice')).not.toBeInTheDocument();
});

it.each([
  ['', 'building', 'Отменить сборку'],
  ['cancel', 'building', 'Отменить сборку'],
  ['build', undefined, 'Собрать черновик'],
  ['final', undefined, 'Проверить финал'],
])('keeps build progress in one strip during %s/%s', (busy, state, buttonName) => {
  const document = makeDocument(busy);
  document.build = state ? { build_id: 'build-1', state } : null;
  const view = render(<ChakraProvider theme={theme}>
    <PdfStudioToolbar document={document} projects={[]} blocked={Boolean(busy)} running={Boolean(state)} onPanel={jest.fn()} />
    <PdfBuildActivity document={document} />
  </ChakraProvider>);
  expect(view.container.querySelectorAll('.chakra-spinner')).toHaveLength(1);
  expect(screen.getByTestId('pdf-studio-toolbar').querySelector('.chakra-spinner')).toBeNull();
  const button = screen.getByRole('button', { name: buttonName, exact: true });
  if (busy) {
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  } else {
    fireEvent.click(button);
    expect(document.cancelBuild).toHaveBeenCalledTimes(1);
  }
});
