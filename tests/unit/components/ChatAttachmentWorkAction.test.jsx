import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import MessageAttachments from '@features/chat/components/MessageAttachments';
import ComposerAttachments from '@features/chat/components/composer/ComposerAttachments';

const attachments = [
  { file_id: 'file-1', filename: 'one.txt', file_type: 'text' },
  { file_id: 'file-2', filename: 'two.txt', file_type: 'text' },
];

describe('attachment Work action', () => {
  it.each([
    ['saved message', <MessageAttachments attachments={attachments} onOpenWork={jest.fn()} />],
    ['composer', <ComposerAttachments attachments={attachments} onOpenWork={jest.fn()} onRemove={jest.fn()} />],
  ])('renders one honest group action for a %s', (_name, component) => {
    render(<ChakraProvider>{component}</ChakraProvider>);

    const action = screen.getByRole('button', { name: 'Открыть работу с вложениями: 2' });
    expect(action).toBeInTheDocument();
    expect(screen.getAllByText('Открыть работу')).toHaveLength(1);
    fireEvent.click(action);
  });
});
