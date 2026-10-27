import { render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import CodeSyntax, { CODE_HIGHLIGHT_LIMIT } from '@shared/controls/CodeSyntax';
import CodeBlock from '@features/chat/components/CodeBlock';
import { ideCodeLanguage } from '@features/workspace-room/model/ideCodeLanguage';

it.each([['src/main.PY', 'python'], ['Dockerfile.dev', 'docker'], ['src/view.tsx', 'tsx'], ['data.yml', 'yaml'], ['README.md', 'markdown'], ['unknown.bin', null], ['.gitignore', null], ['constructor', null], ['example.__proto__', null]])('chooses a supported grammar for %s', (path, language) => {
  expect(ideCodeLanguage(path)).toBe(language);
});

it('renders actual syntax tokens and optional line numbers without interpreting source HTML', () => {
  const { container } = render(<CodeSyntax language="javascript" value={'const example = "<script>private</script>";\nreturn example;'} showLineNumbers />);
  expect(container.querySelector('.token')).toHaveTextContent('const');
  expect(container.querySelector('.token').style.color).not.toBe('');
  expect(container.querySelector('script')).toBeNull();
  expect(container).toHaveTextContent('<script>private</script>');
  expect(container.querySelector('.linenumber')).not.toBeNull();
});

it('keeps unknown languages and large files literal without expensive tokenization', () => {
  const view = render(<CodeSyntax language="unknown" value="<script>not executable</script>" />);
  expect(screen.getByText('<script>not executable</script>')).toBeVisible();
  expect(view.container.querySelector('.token')).toBeNull();
  view.rerender(<CodeSyntax language="javascript" value={'a'.repeat(CODE_HIGHLIGHT_LIMIT + 1)} />);
  expect(view.container.querySelector('.token')).toBeNull();
});

it('preserves the existing Chat code block and its copy action with shared grammars', () => {
  const { container } = render(<ChakraProvider><CodeBlock language="python" value={'def greet():\n    return "hello"'} /></ChakraProvider>);
  expect(screen.getByRole('button', { name: 'Копировать' })).toBeVisible();
  expect(container.querySelector('code')).toHaveTextContent('def greet():');
  expect(container.querySelector('.token')).not.toBeNull();
});
