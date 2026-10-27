import React from 'react';
import { render, screen } from '@testing-library/react';
import { Box, ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import { PROSE_SX } from '../../../src/features/chat/page/proseStyles';
import MockMarkdown from '../../../src/features/platform/components/MockMarkdown';

// This unit owns CSS insertion/heading rhythm, not the ESM Markdown parser.
jest.mock('react-markdown', () => function MarkdownFixture() {
  return <><style>{'.synthetic-style { display: block; }'}</style><h1>Первый заголовок</h1><p>Вводный абзац</p><h2>Следующий раздел</h2></>;
});
jest.mock('remark-gfm', () => () => {});
jest.mock('remark-breaks', () => () => {});
jest.mock('../../../src/features/platform/components/MockCodeBlock', () => () => null);

it.each(['chat', 'platform'])('keeps %s heading rhythm without unsafe first-child selectors', (surface) => {
  const errors = jest.spyOn(console, 'error');
  try {
    render(<ChakraProvider theme={theme}>{surface === 'chat' ? <Box sx={PROSE_SX}>
      <style>{'.synthetic-style { display: block; }'}</style>
      <h1>Первый заголовок</h1><p>Вводный абзац</p><h2>Следующий раздел</h2>
    </Box> : <MockMarkdown content={'# Первый заголовок\n\nВводный абзац\n\n## Следующий раздел'} />}</ChakraProvider>);
    const heading = screen.getByRole('heading', { name: 'Первый заголовок' });
    expect(heading.matches(':not(style) ~ h1')).toBe(false);
    expect(getComputedStyle(heading).marginTop).toBe('0px');
    const later = screen.getByRole('heading', { name: 'Следующий раздел' });
    expect(later.matches(':not(style) ~ h2')).toBe(true);
    // jsdom does not model this grouped :not() cascade's specificity correctly.
    // Check the emitted matching rule here; Playwright owns computed spacing.
    const rules = Array.from(document.styleSheets).flatMap((sheet) => Array.from(sheet.cssRules));
    expect(rules.some((rule) => rule.selectorText?.includes(':not(style)')
      && rule.selectorText.includes('~h2')
      && rule.style.getPropertyValue('margin-top') === '1.2em')).toBe(true);
    expect(errors.mock.calls.some((call) => call.some((value) => String(value).includes('pseudo class ":first-child"')))).toBe(false);
  } finally { errors.mockRestore(); }
});
