import React from 'react';
import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkHistoryPanel } from '@features/workspace-room/components/WorkHistoryPanel';

describe('WorkHistoryPanel', () => {
  it('renders only closed snapshot labels and abbreviated refs', () => {
    render(
      <ChakraProvider>
        <WorkHistoryPanel
          history={[
            { ref: '1234567890abcdef', message: 'user_edit' },
            { ref: 'beefbeef76543210', message: 'document_authoring' },
            { ref: 'fedcba0987654321', message: 'unexpected_raw_value' },
          ]}
          busy=""
          onPreviewRevert={jest.fn()}
        />
      </ChakraProvider>,
    );

    expect(screen.getByText('Правка пользователя')).toBeInTheDocument();
    expect(screen.getByText('Правка документа')).toBeInTheDocument();
    expect(screen.getByText('Снимок рабочего места')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('12345678');
    expect(document.body).not.toHaveTextContent('1234567890abcdef');
    expect(document.body).not.toHaveTextContent('unexpected_raw_value');
  });
});
