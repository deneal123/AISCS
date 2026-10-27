import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfNewDocumentDialog } from '@features/workspace-room/components/PdfNewDocumentDialog';

const profiles = [{ profile_id: 'generic_document', label: 'Документ' }, { profile_id: 'beamer_presentation', label: 'Презентация' }];

test('creates a separate presentation with local format choices and deterministic initial content', async () => {
  const createProject = jest.fn().mockResolvedValue({ path: 'new' });
  const onClose = jest.fn();
  render(<ChakraProvider><PdfNewDocumentDialog document={{ profiles, createProject }} onClose={onClose} /></ChakraProvider>);
  const select = screen.getByRole('combobox', { name: 'Формат нового документа' });
  fireEvent.keyDown(select, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'Презентация', exact: true }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Создать документ', exact: true })));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(createProject).toHaveBeenCalledWith(expect.objectContaining({ profileId: 'beamer_presentation',
    mode: 'draft', locale: 'ru-RU', initializeContent: true, path: expect.stringMatching(/^documents\/document-/) }));
});

test('retains the original destination after an unconfirmed create instead of making a second project', async () => {
  const createProject = jest.fn().mockResolvedValue(null);
  const onClose = jest.fn();
  render(<ChakraProvider><PdfNewDocumentDialog document={{ profiles, createProject }} onClose={onClose} /></ChakraProvider>);
  const button = screen.getByRole('button', { name: 'Создать документ', exact: true });
  await act(async () => fireEvent.click(button));
  expect(await screen.findByRole('alert')).toHaveTextContent('Создание не подтверждено');
  await act(async () => fireEvent.click(button));
  await waitFor(() => expect(createProject).toHaveBeenCalledTimes(2));
  expect(createProject.mock.calls[1][0].path).toBe(createProject.mock.calls[0][0].path);
  expect(onClose).not.toHaveBeenCalled();
});

test('offers explicit format recovery and selects a default when the catalog arrives', async () => {
  const createProject = jest.fn();
  const loadProfiles = jest.fn();
  const view = render(<ChakraProvider><PdfNewDocumentDialog document={{ profiles: [],
    profilesState: 'unavailable', loadProfiles, createProject }} onClose={jest.fn()} /></ChakraProvider>);
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить форматы');
  expect(screen.getByRole('button', { name: 'Создать документ', exact: true })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку форматов', exact: true }));
  expect(loadProfiles).toHaveBeenCalledTimes(1);
  view.rerender(<ChakraProvider><PdfNewDocumentDialog document={{ profiles,
    profilesState: 'ready', loadProfiles, createProject }} onClose={jest.fn()} /></ChakraProvider>);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Создать документ', exact: true })).toBeEnabled());
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(createProject).not.toHaveBeenCalled();
});
