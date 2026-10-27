import React from 'react';
import { render } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatPageLayout from '@features/chat/page/ChatPageLayout';
import { typography } from '@theme/tokens';
import { CHAT_FONT_FAMILY } from '@features/chat/constants/theme';

describe('ChatPageLayout smoke', () => {
  it('renders layout snapshot', () => {
    const { asFragment } = render(
      <ChakraProvider>
        <ChatPageLayout>content</ChatPageLayout>
      </ChakraProvider>,
    );
    expect(CHAT_FONT_FAMILY).toBe(typography.fontFamily.primary);
    expect(asFragment()).toMatchSnapshot();
  });
});
