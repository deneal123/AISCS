import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import { WorkspaceEditor } from '@features/workspace-room/components/WorkspaceEditor';

it('keeps the local buffer editable during an agent command but rejects Save and Ctrl+S', () => {
  const save = jest.fn(); const change = jest.fn();
  render(<ChakraProvider theme={theme}><WorkspaceEditor variant="ide"
    file={{ path: 'hello.py', content: 'local', fence: 1, truncated: false }} dirty
    writeBlocked onSave={save} onChange={change} /></ChakraProvider>);
  const input = screen.getByRole('textbox', { name: 'Содержимое hello.py' });
  expect(input).not.toHaveAttribute('readonly');
  fireEvent.change(input, { target: { value: 'new local' } });
  expect(change).toHaveBeenCalledWith('new local');
  fireEvent.keyDown(input, { key: 's', ctrlKey: true });
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Записать в среду' })).toBeDisabled();
});
