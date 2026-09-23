import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatMessageItem from '@features/chat/components/ChatMessageItem';

jest.mock('@features/chat/components/MessageRenderer', () => () => null);

describe('Document Forge recovery actions', () => {
  it('offers Work and checkpoint retry only for a saved failed project', () => {
    const onOpenWork = jest.fn();
    const regenerateMessage = jest.fn();
    render(
      <ChakraProvider>
        <ChatMessageItem
          message={{
            id: 'agent-1',
            type: 'agent',
            content: 'Не удалось подготовить структуру документа.',
            timestamp: new Date().toISOString(),
            metadata: {
              document_outcome: 'failed',
              document_project_saved: true,
            },
          }}
          isLastMessage
          copyMessage={jest.fn()}
          regenerateMessage={regenerateMessage}
          onOpenWork={onOpenWork}
        />
      </ChakraProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Открыть в Работе' }));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить с черновика' }));

    expect(onOpenWork).toHaveBeenCalledTimes(1);
    expect(regenerateMessage).toHaveBeenCalledWith('agent-1');
  });

  it('offers an explicit confirmed research route for an evidence-blocked draft', () => {
    const onOpenWork = jest.fn();
    const regenerateMessage = jest.fn();
    render(
      <ChakraProvider>
        <ChatMessageItem
          message={{
            id: 'agent-evidence',
            type: 'agent',
            content: 'Черновик сохранён, но источников недостаточно.',
            timestamp: new Date().toISOString(),
            metadata: {
              document_outcome: 'draft_ready',
              document_failure_code: 'evidence_incomplete',
              document_project_saved: true,
            },
          }}
          isLastMessage
          copyMessage={jest.fn()}
          regenerateMessage={regenerateMessage}
          onOpenWork={onOpenWork}
        />
      </ChakraProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Добавить источники в Работе' }));
    fireEvent.click(screen.getByRole('button', {
      name: 'Исследовать источники и подготовить финал',
    }));

    expect(onOpenWork).toHaveBeenCalledTimes(1);
    expect(regenerateMessage).toHaveBeenCalledWith(
      'agent-evidence',
      undefined,
      'research_pdf_document',
    );
  });
});
